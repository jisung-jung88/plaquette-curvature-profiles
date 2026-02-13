r"""
diagonal_model_family_ibm_subgraph.py
=========================================

[WHAT THIS SCRIPT DOES]
----------------------
This script materializes (writes) diagonal_model.yaml files for the "hardware instantiation"
track described in our paper strategy:

  - Main (simulation) prior: 2D grid graph + radius-r spectator rule
  - Hardware (IBM) instantiation: IBM device coupling graph subgraph + SAME radius-r rule

In this file we only handle the hardware instantiation part:
  1) Load an IBM coupling map (directed edges) for a chosen backend (or read from a file).
  2) Select a *connected* physical subgraph of size n_max that contains a chosen physical
     seed edge (p0,p1). This is our "base" graph G_{n_max}^{phys}.
  3) Define a deterministic *ordering* of those physical qubits so that the first n qubits
     form a nested chain of induced subgraphs:
         G_2 ⊂ G_3 ⊂ ... ⊂ G_{n_max}
     This makes an n-sweep comparable and reproducible.
  4) Map those physical qubits to logical indices 0..n_max-1:
         logical 0 -> physical p0
         logical 1 -> physical p1
         ...
     The YAML we emit uses logical indices. (Your qiskit_runner should read the mapping
     and set initial_layout accordingly.)
  5) For each n in [n_min..n_max], emit diagonal_model_n{n}.yaml in your project schema:
         version: "0.1"
         n: <int>
         bit_order: "lsb"
         diagonal_components:
           source: "analytic"
           analytic:
             kind: "pauli_z_sum"
             terms: [...]
           explicit: null

[WHY WE MATERIALIZE YAML INSTEAD OF "COMPUTE ON THE FLY"]
--------------------------------------------------------
- Reproducibility: the YAML is a frozen contract; same file => same φ(z) model.
- Transparency: reviewers/collaborators can inspect the exact model terms.
- Tooling: sim_runner and qiskit_runner can share identical input spec conventions.

[HOW THIS CONNECTS TO κ-LITMUS]
-------------------------------
We work with Z-diagonal unitaries:
    U = diag(exp(i * φ(z)))    for z ∈ {0,1}^n

Under analytic.kind="pauli_z_sum", we define:
    φ(z) = Σ_S  c_S  Π_{q∈S} s_q,    s_q = (-1)^{z_q} ∈ {+1,-1}

κ-profile logic:
  - With only 2-local ZZ terms, κ_{ij}(z_rest) is constant in z_rest (flat).
  - Context dependence of κ_{ij} requires higher-order terms that include BOTH i and j,
    e.g., Z_i Z_j Z_k.

In the paper's hardware corroboration we do NOT need a huge system.
We just want "qualitative trend consistency" between simulation prior and a real device.
To minimize SWAP/compilation artifacts, we use the device coupling graph itself as Layer 1.

[LAYERED DESIGN (MATCHES YOUR PAPER STORY)]
------------------------------------------
Layer 1: Graph G_n  (hardware/placement assumption)
  - Here: G_n is an induced subgraph of the IBM coupling map (undirected for distance).

Layer 2: Diagnostic edge (0,1)
  - We always diagnose the logical pair (0,1).
  - On hardware, (0,1) corresponds to a chosen physical seed edge (p0,p1).

Layer 3: Spectator rule (radius-r on G_{n_max})
  - We define spectators as qubits within graph distance <= r(n) from {0,1}.
  - IMPORTANT: to keep "prefix stability" for an n-sweep, we compute distances on the
    BASE graph G_{n_max}, not on each smaller G_n. This avoids distance changes as we
    add nodes, and makes the rule monotone.

[MODEL FAMILY (HARDWARE INSTANTIATION)]
--------------------------------------
We emit two classes of terms:

(A) Baseline 2-local ZZ on edges of G_n:
      φ_baseline(z) = Σ_{(u,v)∈E(G_n)} J_uv * s_u*s_v
  This makes the prior look like a realistic 2-local coupling model on the device graph.

(B) Parasitic 3-local residues attached ONLY to the diagnostic edge (0,1):
      φ_residue(z) = Σ_{k ∈ N_01(r(n))} B_k * ε_k * s_0*s_1*s_k

  where:
    - N_01(r(n)) is radius-r neighborhood (on G_{n_max}) around {0,1}
    - B_k ~ Bernoulli(p(dist_k))  (sparse)
    - ε_k ~ Normal(0, σ3^2)        (weak), σ3 = eta3 * |J_01|
    - p(dist) = min(1, lambda3 / (dist+1)^alpha_dist)  (distance-decay)

This lets κ_{01} become more context-dependent as r(n) increases (or as more nodes are
included), while preserving a physically plausible "local influence" narrative.

[REPRODUCIBILITY / PREFIX PROPERTY]
----------------------------------
We make (on/off, coefficient) for each term depend ONLY on (seed, tag, indices):
  - No Python hash() (salted per-process).
  - No n inside RNG keys.
  - Terms for a given (u,v) edge or (0,1,k) triple are deterministic once the base
    subgraph and logical mapping are fixed.

Caveat:
  If you change the chosen physical subgraph or the ordering (layout), the logical indices
  represent different physical qubits, so the generated coefficients change. That is fine,
  as long as the choice procedure itself is documented and deterministic.

[INPUT OPTIONS FOR THE COUPLING MAP]
------------------------------------
You can supply the coupling map in two ways:

1) From a file (recommended for reproducibility):
   --coupling-map-file <path>
   - JSON: either a list like [[0,1],[1,2],...] OR a dict containing "coupling_map".
   - YAML: similar structure.

2) From a live backend (optional):
   --backend <backend_name>
   This requires that you have IBM credentials configured in your environment.
   We keep this as a "best effort" convenience; for papers, prefer file input.

[OUTPUT]
--------
For each n in [n_min..n_max], we write:
  <out_dir>/diagonal_model_ibm_subgraph_n{n}.yaml

We also embed a small "hardware_meta" block at top-level that records the logical->physical
mapping. ModelProvider ignores unknown keys, but qiskit_runner can use it for initial_layout.

"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional

import numpy as np
import yaml


# ----------------------------
# Hyperparameters / knobs
# ----------------------------

@dataclass(frozen=True)
class FamilyParams:
    seed: int = 12345

    # Baseline 2-local coefficients on graph edges (phi semantics):
    J0: float = 0.25
    sigma_J: float = 0.00  # keep 0 for clean baseline; can set small value if desired

    # Weak parasitic residue scale:
    eta3: float = 0.20  # sigma3 = eta3 * |J01|

    # Sparsity + distance decay for 3-local residues:
    lambda3: float = 0.8
    alpha_dist: float = 1.0

    # Radius schedule r(n):
    radius_rule: str = "log2"  # "fixed" | "log2" | "loglog2"
    radius_fixed: int = 1
    radius_cap: int = 999


# ----------------------------
# Stable RNG (no hash, no n)
# ----------------------------

_TAG = {"J": 1, "on3": 2, "eps3": 3}

def rng(seed: int, tag: str, *idx: int) -> np.random.Generator:
    if tag not in _TAG:
        raise ValueError(f"unknown RNG tag={tag!r}")
    entropy = [int(seed), int(_TAG[tag]), *[int(x) for x in idx]]
    ss = np.random.SeedSequence(entropy)
    return np.random.default_rng(ss)

COEFF_EPS = 1e-15

def clamp_nonzero(x: float) -> float:
    if abs(x) >= COEFF_EPS:
        return float(x)
    return float(COEFF_EPS if x >= 0 else -COEFF_EPS)


# ----------------------------
# Utility: radius schedule
# ----------------------------

def radius_of_n(n: int, p: FamilyParams) -> int:
    if p.radius_rule == "fixed":
        r = int(p.radius_fixed)
    elif p.radius_rule == "log2":
        r = int(math.ceil(math.log2(max(2, n))))
    elif p.radius_rule == "loglog2":
        inner = max(2.0, math.log2(max(2, n)))
        r = int(math.ceil(math.log2(inner)))
    else:
        raise ValueError(f"unknown radius_rule={p.radius_rule!r}")

    r = max(1, r)
    r = min(int(p.radius_cap), r)
    return r


def p_on(dist_k: int, p: FamilyParams) -> float:
    denom = float((dist_k + 1) ** p.alpha_dist)
    return float(min(1.0, p.lambda3 / denom))


# ----------------------------
# Coupling map loading
# ----------------------------

def load_coupling_map_from_file(path: Path) -> Tuple[List[Tuple[int, int]], Optional[str]]:
    """
    Load directed edges from JSON/YAML file.

    Supported formats:
      - JSON list: [[u,v],[u,v],...]
      - JSON dict: {"coupling_map": [[u,v],...], "backend": "...", ...}
      - YAML list or dict with same convention

    Returns:
      (edges, backend_name) where backend_name may be None if not in file.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    backend_name: Optional[str] = None

    if isinstance(data, dict) and "coupling_map" in data:
        edges = data["coupling_map"]
        # Support both "backend" and "backend_name" keys
        backend_name = data.get("backend_name", data.get("backend", None))
    elif isinstance(data, list):
        edges = data
    else:
        raise ValueError("Unsupported coupling-map file schema. Provide list or dict with 'coupling_map'.")

    out: List[Tuple[int, int]] = []
    for e in edges:
        if not (isinstance(e, (list, tuple)) and len(e) == 2):
            raise ValueError(f"Bad edge entry: {e!r}")
        u, v = int(e[0]), int(e[1])
        out.append((u, v))
    return out, backend_name


def load_coupling_map_from_backend(backend_name: str) -> List[Tuple[int, int]]:
    """
    Best-effort: load coupling map from an IBM backend via qiskit-ibm-runtime.

    For paper-grade reproducibility, prefer --coupling-map-file so you can commit the
    coupling_map list alongside the run.

    This function is optional and may require your IBM account configuration.
    """
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "qiskit_ibm_runtime not available. Use --coupling-map-file instead."
        ) from e

    # This expects credentials already saved (service = QiskitRuntimeService()).
    service = QiskitRuntimeService()
    backend = service.backend(backend_name)

    # Different Qiskit versions expose coupling map differently; configuration().coupling_map
    # is the most common.
    cfg = backend.configuration()
    cmap = getattr(cfg, "coupling_map", None)
    if cmap is None:
        raise RuntimeError("backend.configuration().coupling_map not found; use --coupling-map-file.")
    return [(int(u), int(v)) for (u, v) in cmap]


# ----------------------------
# Graph utilities (undirected)
# ----------------------------

def to_undirected_edges(directed_edges: List[Tuple[int, int]], require_bidirectional: bool) -> Set[Tuple[int, int]]:
    """
    Convert directed coupling edges to an undirected edge set (u < v).
    If require_bidirectional=True, keep only edges that exist in both directions.
    """
    dir_set = set((int(u), int(v)) for (u, v) in directed_edges)

    und: Set[Tuple[int, int]] = set()
    for (u, v) in dir_set:
        a, b = (u, v) if u < v else (v, u)
        if a == b:
            continue
        if require_bidirectional:
            if (a, b) in dir_set and (b, a) in dir_set:
                und.add((a, b))
        else:
            und.add((a, b))
    return und


def build_adjacency_from_edges(edges_und: Set[Tuple[int, int]]) -> Dict[int, Set[int]]:
    adj: Dict[int, Set[int]] = {}
    for (u, v) in edges_und:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)
    return adj


def bfs_order_from_seed_edge(adj: Dict[int, Set[int]], seed_a: int, seed_b: int, n_max: int) -> List[int]:
    """
    Deterministically pick a connected set of n_max nodes containing (seed_a, seed_b),
    using BFS expansion from {seed_a, seed_b}.

    Determinism: neighbors are processed in sorted order.

    Returns physical node order list length n_max.
    """
    if seed_a == seed_b:
        raise ValueError("seed edge must have two distinct nodes")

    if seed_a not in adj or seed_b not in adj:
        raise ValueError("seed nodes not present in coupling graph adjacency")

    if seed_b not in adj.get(seed_a, set()):
        # seed edge must exist as an undirected edge
        raise ValueError(f"seed edge ({seed_a},{seed_b}) not an undirected edge in this coupling graph")

    visited: Set[int] = set()
    order: List[int] = []

    # Ensure seed nodes are first (in the exact order we want).
    for s in (seed_a, seed_b):
        if s not in visited:
            visited.add(s)
            order.append(s)

    # BFS queue
    q: List[int] = [seed_a, seed_b]
    head = 0
    while head < len(q) and len(order) < n_max:
        u = q[head]
        head += 1
        for v in sorted(adj.get(u, set())):
            if v in visited:
                continue
            visited.add(v)
            order.append(v)
            q.append(v)
            if len(order) >= n_max:
                break

    if len(order) < n_max:
        raise ValueError(
            f"Could not find {n_max} connected nodes from seed edge ({seed_a},{seed_b}). "
            f"Only found {len(order)}."
        )
    return order


def induced_edges_on_order(edges_und: Set[Tuple[int, int]], phys_order: List[int]) -> List[Tuple[int, int]]:
    """
    Given a physical node ordering (length n_max), build the induced undirected edge list
    (logical indices) for the base graph G_{n_max}.

    Returns edges as (u,v) with u<v in logical indices.
    """
    phys2log = {p: i for (i, p) in enumerate(phys_order)}
    out: Set[Tuple[int, int]] = set()

    for (a, b) in edges_und:
        if a in phys2log and b in phys2log:
            u = phys2log[a]
            v = phys2log[b]
            if u == v:
                continue
            if u < v:
                out.add((u, v))
            else:
                out.add((v, u))

    return sorted(out)


def bfs_distances_logical(n_max: int, base_edges: List[Tuple[int, int]], sources: List[int]) -> List[int]:
    """
    BFS distances on the base logical graph G_{n_max}.
    This is used as the "physical distance label" for all smaller n to preserve prefix stability.
    """
    INF = 10**9
    adj = [set() for _ in range(n_max)]
    for (u, v) in base_edges:
        adj[u].add(v)
        adj[v].add(u)

    dist = [INF] * n_max
    q: List[int] = []
    for s in sources:
        dist[s] = 0
        q.append(s)

    head = 0
    while head < len(q):
        u = q[head]
        head += 1
        du = dist[u]
        for v in sorted(adj[u]):
            if dist[v] > du + 1:
                dist[v] = du + 1
                q.append(v)

    return dist


# ----------------------------
# Terms generation for IBM subgraph family
# ----------------------------

def build_terms_for_n(
    n: int,
    base_edges: List[Tuple[int, int]],
    dist_base: List[int],
    p: FamilyParams,
) -> List[Dict]:
    """
    Build analytic terms for the n-qubit model on the IBM subgraph instantiation.

    Inputs:
      - base_edges: edges of G_{n_max} in logical indices
      - dist_base: distances to {0,1} in G_{n_max} (logical), used for all n
      - n: desired size (<= n_max)

    Output terms:
      - Baseline ZZ on edges in the induced subgraph on nodes [0..n-1]
      - Residue Z0 Z1 Zk for k < n and dist_base[k] <= r(n)

    All randomness uses stable keys independent of n.
    """
    if n < 2:
        raise ValueError("n must be >= 2")
    n_max = len(dist_base)
    if n > n_max:
        raise ValueError(f"n={n} exceeds n_max={n_max}")

    terms: List[Dict] = []

    # Baseline ZZ on induced edges
    for (u, v) in base_edges:
        if u >= n or v >= n:
            continue
        g = rng(p.seed, "J", u, v)
        Jij = p.J0 + p.sigma_J * g.normal()
        terms.append({"c": clamp_nonzero(Jij), "z": [int(u), int(v)]})

    # Compute J01 for sigma3 (must be consistent with baseline coefficient)
    g01 = rng(p.seed, "J", 0, 1)
    J01 = p.J0 + p.sigma_J * g01.normal()
    J01 = clamp_nonzero(J01)
    sigma3 = abs(J01) * float(p.eta3)

    # Residue candidates based on base distances + radius schedule
    r = radius_of_n(n, p)
    for k in range(n):
        if k in (0, 1):
            continue
        dk = dist_base[k]
        if dk > r:
            continue

        pk = p_on(dk, p)
        if pk <= 0.0:
            continue

        gu = rng(p.seed, "on3", 0, 1, k)
        if gu.random() >= pk:
            continue

        ge = rng(p.seed, "eps3", 0, 1, k)
        eps = sigma3 * ge.normal()
        terms.append({"c": clamp_nonzero(eps), "z": [0, 1, int(k)]})

    return terms


def build_yaml_spec(
    n: int,
    p: FamilyParams,
    base_edges: List[Tuple[int, int]],
    dist_base: List[int],
    phys_order: List[int],
    backend_name: Optional[str],
    seed_edge_phys: Tuple[int, int],
) -> Dict:
    """
    Build YAML dictionary in your project schema.

    We include a 'hardware_meta' block with the logical->physical mapping.
    ModelProvider will ignore it; qiskit_runner can use it.
    """
    return {
        "version": "0.1",
        "n": int(n),
        "bit_order": "lsb",
        "hardware_meta": {
            "backend": backend_name,
            "seed_edge_physical": [int(seed_edge_phys[0]), int(seed_edge_phys[1])],
            # logical index -> physical qubit id
            "physical_qubits": [int(x) for x in phys_order[:n]],
            "note": "logical 0,1 correspond to the physical seed edge above",
        },
        "family_meta": {
            "family": "ibm_subgraph_radius_r_v1",
            **asdict(p),
            "n_max_base": len(dist_base),
        },
        "diagonal_components": {
            "source": "analytic",
            "analytic": {
                "kind": "pauli_z_sum",
                "terms": build_terms_for_n(n, base_edges, dist_base, p),
            },
            "explicit": None,
        },
    }


def write_yaml(path: Path, spec: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, sort_keys=False, default_flow_style=False)


# ----------------------------
# CLI
# ----------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate diagonal_model.yaml files for an IBM coupling-subgraph instantiation (radius-r)."
    )
    ap.add_argument("--out-dir", type=str, default="models_ibm", help="Output directory for YAML files")
    ap.add_argument("--n-min", type=int, default=2)
    ap.add_argument("--n-max", type=int, default=7)

    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--J0", type=float, default=0.25)
    ap.add_argument("--sigma-J", type=float, default=0.00)

    ap.add_argument("--eta3", type=float, default=0.20)
    ap.add_argument("--lambda3", type=float, default=0.8)
    ap.add_argument("--alpha-dist", type=float, default=1.0)

    ap.add_argument("--radius-rule", type=str, default="log2", choices=["fixed", "log2", "loglog2"])
    ap.add_argument("--radius-fixed", type=int, default=1)
    ap.add_argument("--radius-cap", type=int, default=999)

    # Coupling map input
    ap.add_argument("--coupling-map-file", type=str, default=None,
                    help="Path to JSON/YAML containing coupling_map (directed edges). Recommended.")
    ap.add_argument("--backend", type=str, default=None,
                    help="IBM backend name (optional convenience; requires qiskit-ibm-runtime configured).")

    ap.add_argument("--require-bidirectional", action="store_true",
                    help="Keep only edges present in both directions in coupling_map.")

    # Subgraph selection
    ap.add_argument("--seed-edge", type=str, required=True,
                    help='Physical seed edge as "u,v" that must exist in the coupling graph.')

    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.n_min < 2 or args.n_max < args.n_min:
        raise SystemExit("Invalid n range: require 2 <= n_min <= n_max")

    if args.coupling_map_file is None and args.backend is None:
        raise SystemExit("Provide either --coupling-map-file or --backend")

    # Load coupling map (directed edges)
    backend_name = args.backend
    if args.coupling_map_file is not None:
        directed, file_backend_name = load_coupling_map_from_file(Path(args.coupling_map_file))
        # Use backend name from file if not overridden by --backend
        if backend_name is None:
            backend_name = file_backend_name
    else:
        directed = load_coupling_map_from_backend(args.backend)

    # Parse seed edge
    try:
        a_str, b_str = args.seed_edge.split(",")
        seed_a, seed_b = int(a_str.strip()), int(b_str.strip())
    except Exception:
        raise SystemExit('Invalid --seed-edge. Expected "u,v", e.g. --seed-edge 3,5')

    # Build undirected graph from coupling map
    edges_und = to_undirected_edges(directed, require_bidirectional=bool(args.require_bidirectional))
    adj = build_adjacency_from_edges(edges_und)

    # Pick connected base physical subgraph of size n_max (BFS expansion)
    phys_order = bfs_order_from_seed_edge(adj, seed_a, seed_b, n_max=int(args.n_max))

    # Convert induced base edges to logical indices 0..n_max-1
    base_edges = induced_edges_on_order(edges_und, phys_order)

    # Distances on the base logical graph (used for all n)
    dist_base = bfs_distances_logical(len(phys_order), base_edges, sources=[0, 1])

    # Build family params
    p = FamilyParams(
        seed=int(args.seed),
        J0=float(args.J0),
        sigma_J=float(args.sigma_J),
        eta3=float(args.eta3),
        lambda3=float(args.lambda3),
        alpha_dist=float(args.alpha_dist),
        radius_rule=str(args.radius_rule),
        radius_fixed=int(args.radius_fixed),
        radius_cap=int(args.radius_cap),
    )

    out_dir = Path(args.out_dir)
    for n in range(int(args.n_min), int(args.n_max) + 1):
        spec = build_yaml_spec(
            n=n,
            p=p,
            base_edges=base_edges,
            dist_base=dist_base,
            phys_order=phys_order,
            backend_name=backend_name,
            seed_edge_phys=(seed_a, seed_b),
        )
        # Include backend name in filename if available
        if backend_name:
            out_path = out_dir / f"diagonal_model_{backend_name}_subgraph_n{n}.yaml"
        else:
            out_path = out_dir / f"diagonal_model_ibm_subgraph_n{n}.yaml"
        write_yaml(out_path, spec)
        print(f"Wrote {out_path} (r(n)={radius_of_n(n,p)})")

    print("\nPhysical layout (logical -> physical):")
    for li, pi in enumerate(phys_order):
        print(f"  logical {li} -> physical {pi}")


if __name__ == "__main__":
    main()