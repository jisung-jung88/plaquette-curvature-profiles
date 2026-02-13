r"""
diagonal_model_family_grid_radius.py
=========================================

[WHY THIS FILE EXISTS]
----------------------
This script generates *concrete* `diagonal_model.yaml` files for a diagonal Hamiltonian
family used as the **simulation prior** in the κ‑litmus project.

Why write YAML instead of computing coefficients on-the-fly?
  - Reproducibility: a YAML spec is a "frozen contract" for reviewers/collaborators.
  - Tooling unification: *the same YAML* can drive both simulation and QPU runs
    (e.g., `sim_runner.py` and `qiskit_runner.py`).
  - Debugging: if a figure looks wrong, we can inspect the exact model terms.

[κ‑LITMUS CONTEXT (what the YAML means)]
---------------------------------------
We work with Z‑diagonal unitaries

    U = diag( exp(i * φ(z)) ),   z ∈ {0,1}^n.

In the YAML schema we use:

    diagonal_components.source = "analytic"
    diagonal_components.analytic.kind = "pauli_z_sum"

Meaning:

    φ(z) = Σ_S  c_S  Π_{q∈S} s_q,
    where s_q = (-1)^{z_q} ∈ {+1, -1}.

κ‑profile logic (core narrative for the paper):
  - If φ contains only 2‑local ZZ terms (Z_i Z_j), then κ_{ij}(z_rest)
    is constant in z_rest ("flat profile") for each fixed pair (i,j).
  - Context dependence of κ_{ij} requires higher‑order diagonal terms that include
    BOTH i and j (e.g., Z_i Z_j Z_k).

[WHAT THIS FAMILY IS TRYING TO SHOW (paper "money plot")]
----------------------------------------------------------
We want a clean simulation story:
  - Fix a single diagnostic pair (0,1).
  - Sweep n = 2,3,4,5,6,7.
  - Observe that the κ‑profile variance for *the same pair* (0,1) can grow with n
    when we inject a controlled amount of higher‑order (3‑local) residue.

To do that without assuming fully‑global spectators, we use a "local-ish" spectator rule:

    N_01(r) = { k : dist(k, {0,1}) <= r(n) } \ {0,1}

and let the radius r(n) grow slowly (e.g., ceil(log2 n)).

[MODEL TERMS GENERATED]
-----------------------
(A) Baseline 2‑local ZZ on a sparse graph G_n (a 2D grid / lattice):

    H2 ~ Σ_{(u,v) ∈ E(G_n)} J_uv Z_u Z_v

(B) Parasitic 3‑local residue *attached ONLY to the diagnostic edge (0,1)*:

    H3 ~ Σ_{k ∈ N_01(r(n))}  B_k * ε_k * Z_0 Z_1 Z_k

  - B_k ~ Bernoulli(p_k) (sparse on/off)
  - ε_k ~ Normal(0, σ3^2) where σ3 = eta3 * |J_01| (weak relative leakage)
  - p_k decays with distance so nearer spectators are more likely:

        p_k = min(1, lambda3 / (dist(k,{0,1}) + 1)^alpha_dist )

[REPRODUCIBILITY / PREFIX RULE (non‑negotiable)]
------------------------------------------------
We enforce:
  - Same seed => identical YAML on every machine/run.
  - Growing n does NOT change coefficients for already‑existing terms.

Implementation details:
  - Every random decision is derived only from (seed, tag, indices).
  - No Python `hash()` (salted per process).
  - No `n` in RNG keys (prefix stability).
  - The only n‑dependence is structural:
      - which nodes/edges exist in G_n,
      - which spectators are allowed (dist <= r(n)).

================================================================================
IMPORTANT UPDATE (requested change): CENTERED‑GROWTH / BFS‑SHELL INDEXING
================================================================================

**What changed?**
Older versions of this script used a row‑major embedding:

    node -> (x = node % W, y = node // W)

which implicitly pins logical qubits (0,1) to the top‑left corner of the grid.
That makes (0,1) a boundary edge for all n, which can invite "boundary artifact"
criticism (even if the physics/diagnostic idea is not about boundaries).

**New approach (the clean fix):**
We keep the same sparse 2D grid *geometry*, but we change how logical indices are
assigned to grid sites.

We now use **centered‑growth / BFS‑shell indexing** around the diagnostic edge (0,1):

  1) Fix a W×W grid once using n_max (still required for prefix stability).

  2) Choose an "anchor" physical edge near the *center* of the grid, and assign:

        logical 0  -> anchor site A
        logical 1  -> anchor site B  (adjacent to A)

     Deterministic rule used here:
       - A = (cx, cy) where cx = cy = floor((W-1)/2)
       - B = (cx+1, cy) (a horizontal neighbor; always valid for W>=2)

  3) Compute graph distances (BFS shells) from the *set* {A,B}.

  4) Order the remaining sites by increasing distance, i.e. shell 1, shell 2, ...
     and break ties *deterministically* by coordinate lex order.

     Tie‑break rule fixed in this file:
       - sort by (dist, y, x)
         (row-major lexicographic order inside each shell)

  5) Define G_n as the induced subgraph on the first n sites in this order.

**Why this is better (matches the feedback):**
  - The diagnostic edge (0,1) stays near the *center* as n grows.
  - Prefix stability is still guaranteed (we always take a prefix of one fixed order).
  - The growth mechanism matches our IBM hardware script
    (`diagonal_model_family_ibm_subgraph.py`): seed edge + BFS ordering.
  - Therefore boundary artifacts are not intrinsic to κ‑litmus; they were an
    indexing/placement choice.

[IMPORTANT PRACTICAL NOTE: NESTED GRID FAMILY (still applies)]
--------------------------------------------------------------
If you re-choose W = ceil(sqrt(n)) independently for each n,
then grid coordinates change when W changes => the family is NOT prefix‑stable.

So we FIX W using n_max, and for each n we take the induced subgraph on the
first n vertices in the centered-growth BFS order.

USAGE
-----
Generate YAMLs for n=2..7:

  python diagonal_model_family_grid_radius.py --n-min 2 --n-max 7 --out-dir models

Optionally override W (must be >= 2 and satisfy W^2 >= n_max):

  python diagonal_model_family_grid_radius.py --n-min 2 --n-max 7 --grid-width 3 --out-dir models

"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple, Sequence, Optional

import numpy as np
import yaml


# =============================================================================
# Hyperparameters (paper knobs)
# =============================================================================

@dataclass(frozen=True)
class FamilyParams:
    """All tunable knobs for the synthetic diagonal Hamiltonian family."""

    # Global seed.
    # Every coefficient / Bernoulli decision is derived from this.
    seed: int = 12345

    # Diagnostic pair (fixed for the paper story): (0,1).
    # IMPORTANT: in this *centered-growth* script, (0,1) is also the seed edge
    # used to define the BFS-shell indexing. (We validate this in code.)
    i: int = 0
    j: int = 1

    # Baseline 2-local ZZ coefficients on graph edges:
    J0: float = 0.25          # mean baseline coupling strength (phi semantics)
    sigma_J: float = 0.00     # optional spread; keep 0 for a clean baseline

    # Weak parasitic residue scale:
    #   σ3 = eta3 * |J01|, where J01 is the (0,1) ZZ coefficient
    eta3: float = 0.20        # 0.05~0.2 is a typical "weak leakage" regime

    # Sparsity of parasitic terms:
    #   p_k = min(1, lambda3 / (dist+1)^alpha_dist)
    # Bigger lambda3 => more active spectators.
    lambda3: float = 0.8

    # Distance decay exponent for p_k.
    alpha_dist: float = 1.0   # 1.0 is mild decay

    # Radius schedule r(n): how far spectators are allowed to be.
    radius_rule: str = "log2"  # "fixed" | "log2" | "loglog2"
    radius_fixed: int = 1      # used if radius_rule == "fixed"
    radius_cap: int = 999      # optional hard cap


# =============================================================================
# Stable RNG utilities
# =============================================================================

# Numeric tags for independent random streams.
# Using explicit integers avoids Python hash() instability.
_TAG = {
    "J": 1,      # baseline edge coefficients J_uv
    "on3": 2,    # Bernoulli on/off for (i,j,k)
    "eps3": 3,   # Gaussian residue coefficient for (i,j,k)
}


def rng(seed: int, tag: str, *idx: int) -> np.random.Generator:
    """Deterministic RNG for a specific key: (seed, tag, idx...).

    Critical invariants (do NOT break these if you want prefix-stability):
      - Do NOT use python hash()
      - Do NOT include n in idx

    Why "no n"?
      If any RNG key includes n, then when you sweep n the *same* logical term could
      receive a different coefficient (destroying the nested-family narrative).
    """

    if tag not in _TAG:
        raise ValueError(f"unknown RNG tag: {tag}")
    entropy = [int(seed), int(_TAG[tag]), *[int(x) for x in idx]]
    ss = np.random.SeedSequence(entropy)
    return np.random.default_rng(ss)


# =============================================================================
# Layer 1: Sparse graph G_n = 2D grid with CENTERED-GROWTH BFS-SHELL indexing
# =============================================================================

# Coordinate type for the W×W grid.
# We use (x,y) with:
#   x = column index, 0..W-1
#   y = row index,    0..W-1
Coord = Tuple[int, int]


def _coord_to_idx(xy: Coord, width: int) -> int:
    """(x,y) -> linear index in [0, width^2)."""
    x, y = xy
    return int(y) * int(width) + int(x)


def _idx_to_coord(idx: int, width: int) -> Coord:
    """Linear index -> (x,y)."""
    x = int(idx) % int(width)
    y = int(idx) // int(width)
    return (x, y)


def anchor_edge_xy(width: int) -> Tuple[Coord, Coord]:
    """Choose the deterministic "anchor" edge near the grid center.

    This is the key to the centered-growth story:
      - logical qubit 0 is placed on anchor site A
      - logical qubit 1 is placed on anchor site B

    Deterministic rule (so everyone's YAML matches):
      - A = (cx, cy) where cx = cy = floor((W-1)/2)
      - B = (cx+1, cy)

    Notes:
      - B is always valid for W>=2 because cx <= W-2.
      - We intentionally choose a horizontal edge to remove any "arbitrary" degrees
        of freedom that reviewers could poke at.
    """

    if width < 2:
        raise ValueError("width must be >= 2")

    cx = (width - 1) // 2
    cy = (width - 1) // 2
    a = (int(cx), int(cy))
    b = (int(cx + 1), int(cy))
    return a, b


def _neighbors_in_full_grid(idx: int, width: int) -> List[int]:
    """Return 4-neighborhood (Manhattan adjacency) neighbors of a node in the full W×W grid.

    IMPORTANT: This is *not* yet the induced graph G_n. This is the full geometric lattice.
    We use it to compute BFS distances / ordering in a way that is independent of n.
    """

    x, y = _idx_to_coord(idx, width)
    nbrs: List[int] = []

    # left / right
    if x - 1 >= 0:
        nbrs.append(_coord_to_idx((x - 1, y), width))
    if x + 1 < width:
        nbrs.append(_coord_to_idx((x + 1, y), width))

    # up / down
    if y - 1 >= 0:
        nbrs.append(_coord_to_idx((x, y - 1), width))
    if y + 1 < width:
        nbrs.append(_coord_to_idx((x, y + 1), width))

    return nbrs


def _bfs_dist_full_grid(width: int, sources_xy: Sequence[Coord]) -> List[int]:
    """Multi-source BFS distances on the full W×W grid.

    Returns:
      dist_full[idx] = graph distance from the *set* of sources to idx.

    Why multi-source?
      Our diagnostic object is an *edge* (0,1), i.e. a pair of sites.
      We want shells around the *edge*, so we BFS from {A,B}.

    Determinism:
      Distances are unique, independent of queue neighbor ordering.
    """

    n_total = int(width) * int(width)
    INF = 10**9
    dist = [INF] * n_total

    # Initialize queue with sources in a deterministic order.
    q: List[int] = []
    for xy in sources_xy:
        idx = _coord_to_idx(xy, width)
        if dist[idx] > 0:
            dist[idx] = 0
            q.append(idx)

    head = 0
    while head < len(q):
        u = q[head]
        head += 1
        du = dist[u]
        for v in _neighbors_in_full_grid(u, width):
            if dist[v] > du + 1:
                dist[v] = du + 1
                q.append(v)

    return dist


@dataclass(frozen=True)
class CenteredGrowthLayout:
    """Everything about the *fixed* W×W geometry and indexing.

    Think of this as the simulation-side analogue of the hardware script's
    "seed edge + BFS ordering" mechanism.

    Fields
    ------
    width:
      The fixed W used for the whole n-sweep.

    anchor_xy:
      The two grid coordinates where logical qubits 0 and 1 are placed.

    order_xy:
      A tuple of length W^2 listing grid coordinates in the centered-growth order.
      Logical qubit index q is mapped to coordinate order_xy[q].

    dist_shell:
      dist_shell[q] is the distance from the anchor edge (0,1) to qubit q in
      the *full* W×W grid.

      Under centered-growth ordering, this also equals the distance in every
      prefix-induced graph G_n for any q < n.

    base_edges:
      List of undirected edges (u,v) with u < v in the full W×W grid, expressed in
      logical indices under this layout.

      For a given n, E(G_n) is obtained by filtering edges where both endpoints < n.
    """

    width: int
    anchor_xy: Tuple[Coord, Coord]
    order_xy: Tuple[Coord, ...]
    dist_shell: Tuple[int, ...]
    base_edges: Tuple[Tuple[int, int], ...]


@lru_cache(maxsize=None)
def centered_growth_layout(width: int) -> CenteredGrowthLayout:
    """Build (and cache) the centered-growth BFS-shell layout for a given width.

    This function has *no randomness* and depends only on width.
    Caching keeps repeated calls cheap when sweeping many n values.
    """

    if width < 2:
        raise ValueError("width must be >= 2")

    # 1) Choose anchor edge near the center.
    a_xy, b_xy = anchor_edge_xy(width)

    # 2) Compute full-grid distances to the anchor edge.
    dist_full = _bfs_dist_full_grid(width, [a_xy, b_xy])

    # 3) Define the BFS-shell order: sort all sites by (distance, y, x).
    #    - primary key: distance from {A,B}
    #    - tie-break: row-major lex order (y,x)
    all_xy = [_idx_to_coord(idx, width) for idx in range(width * width)]

    def _sort_key(xy: Coord) -> Tuple[int, int, int]:
        x, y = xy
        return (int(dist_full[_coord_to_idx(xy, width)]), int(y), int(x))

    order_xy = tuple(sorted(all_xy, key=_sort_key))

    # Sanity checks: by construction, the first two must be the anchor edge sites.
    # (This guarantees the story "logical 0,1 are the anchor edge".)
    if order_xy[0] != a_xy or order_xy[1] != b_xy:
        raise RuntimeError(
            "Internal error: centered-growth order did not place anchors at indices 0,1. "
            f"Got order[0:2]={order_xy[0:2]}, expected={(a_xy, b_xy)}"
        )

    # 4) Precompute dist_shell by logical index.
    dist_shell = tuple(int(dist_full[_coord_to_idx(xy, width)]) for xy in order_xy)

    # 5) Precompute full-grid undirected edges in *logical index* space.
    #    We do this once, and for each n we take the induced subgraph by filtering.
    coord2log: Dict[Coord, int] = {xy: q for q, xy in enumerate(order_xy)}

    edges: List[Tuple[int, int]] = []
    for y in range(width):
        for x in range(width):
            u = coord2log[(x, y)]

            # Add right edge (x,y) -- (x+1,y)
            if x + 1 < width:
                v = coord2log[(x + 1, y)]
                a, b = (u, v) if u < v else (v, u)
                edges.append((a, b))

            # Add down edge (x,y) -- (x,y+1)
            if y + 1 < width:
                v = coord2log[(x, y + 1)]
                a, b = (u, v) if u < v else (v, u)
                edges.append((a, b))

    edges_sorted = tuple(sorted(edges))

    # Another sanity check: anchor logical edge (0,1) must be a geometric edge.
    if (0, 1) not in edges_sorted:
        raise RuntimeError(
            "Internal error: (0,1) is not an edge in the base grid. "
            "Anchor selection is broken."
        )

    return CenteredGrowthLayout(
        width=int(width),
        anchor_xy=(a_xy, b_xy),
        order_xy=order_xy,
        dist_shell=dist_shell,
        base_edges=edges_sorted,
    )


def grid_edges_for_n(n: int, layout: CenteredGrowthLayout) -> List[Tuple[int, int]]:
    """Return undirected edges (u,v) with u < v in the induced subgraph G_n.

    Because G_n is defined as the induced subgraph on vertices {0,1,...,n-1},
    the edge set is just:

        E(G_n) = { (u,v) in base_edges : u < n and v < n }.

    Implementation detail:
      base_edges are stored with u < v, so the condition v < n is sufficient.
    """

    if n < 2:
        return []
    return [(u, v) for (u, v) in layout.base_edges if v < n]


# =============================================================================
# Layer 3: radius-r neighborhood around {i,j} (here: always {0,1})
# =============================================================================


def radius_of_n(n: int, p: FamilyParams) -> int:
    """Choose r(n).

    We require r(n) to be non-decreasing for a clean n-sweep narrative.

    Supported rules:
      - fixed:   r(n) = radius_fixed
      - log2:    r(n) = ceil(log2 n)
      - loglog2: r(n) = ceil(log2(log2 n))  (very slow)

    The rule is capped by radius_cap and bottomed at r>=1.
    """

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


def spectator_candidates(
    n: int,
    layout: CenteredGrowthLayout,
    i: int,
    j: int,
    r: int,
) -> List[Tuple[int, int]]:
    """List spectators k in G_n within radius r of the diagnostic set {i,j}.

    In this *centered-growth* script we **intend i,j = (0,1)**.

    Because our vertex ordering is by BFS shells around (0,1), the distance from
    {0,1} to any included node k is already encoded as layout.dist_shell[k].

    That lets us implement the spectator rule without re-running BFS for every n.

    Returns:
      A list of (k, dist_k) pairs.
    """

    out: List[Tuple[int, int]] = []
    for k in range(n):
        if k == i or k == j:
            continue
        dk = int(layout.dist_shell[k])
        if dk <= r:
            out.append((k, dk))
    return out


# =============================================================================
# Terms generation: YAML analytic.kind="pauli_z_sum"
# =============================================================================

# ModelProvider validator in this project historically dislikes exactly-zero coefficients.
# (This avoids writing 0.0 which can be interpreted as a missing term.)
COEFF_EPS = 1e-15


def clamp_nonzero(x: float) -> float:
    """Avoid exactly-zero coefficients (ModelProvider treats ~0 as invalid)."""
    if abs(x) >= COEFF_EPS:
        return float(x)
    return float(COEFF_EPS if x >= 0 else -COEFF_EPS)


def p_on(dist_k: int, p: FamilyParams) -> float:
    """Probability that the residue term Z_i Z_j Z_k is present.

    Design intent:
      - As n grows, r(n) grows slowly -> more candidate spectators appear.
      - Among candidates, nearer spectators are more likely to be activated.

    The decay law is intentionally simple (a reviewer-friendly knob):

      p_k = min(1, lambda3 / (dist_k + 1)^alpha_dist).

    Notes:
      - dist_k starts at 1 for immediate neighbors of the diagnostic edge.
      - The "+1" avoids division by zero at the anchor itself (which we exclude anyway).
    """

    denom = float((int(dist_k) + 1) ** float(p.alpha_dist))
    return float(min(1.0, float(p.lambda3) / denom))


def build_terms_for_n(
    n: int,
    width: int,
    p: FamilyParams,
    layout: Optional[CenteredGrowthLayout] = None,
) -> List[Dict]:
    """Build the `terms:` list for a given n.

    This function is the "meat" of the generator.

    It returns a list of dictionaries in the exact YAML schema:
      {"c": <float>, "z": [q0, q1, ...]}

    containing:
      - Baseline 2-local ZZ terms on all edges of G_n.
      - Residue 3-local terms Z_0 Z_1 Z_k for spectators k within radius r(n).

    IMPORTANT invariants:
      - For fixed (seed, indices), coefficients do not change when you sweep n.
      - G_n is nested by construction (prefix of a fixed ordering).
    """

    if n < 2:
        raise ValueError("n must be >= 2")
    if width < 2:
        raise ValueError("grid_width must be >= 2")
    if width * width < n:
        # Not strictly required by math, but it keeps the interpretation
        # "we are embedding into a W×W grid" honest.
        raise ValueError(
            f"grid_width={width} too small for n={n}. "
            "Use width >= ceil(sqrt(n_max)) (or explicitly provide a larger --grid-width)."
        )

    # Enforce that the diagnostic edge is (0,1).
    # Why so strict?
    #   This file's indexing (BFS shells) is *defined around logical qubits 0 and 1*.
    #   If you want a different diagnostic edge, either:
    #     (i) change the indexing to be centered around that edge, or
    #     (ii) use the row-major backup script.
    i, j = (p.i, p.j) if p.i < p.j else (p.j, p.i)
    if (i, j) != (0, 1):
        raise ValueError(
            "This centered-growth generator assumes the diagnostic pair is (0,1). "
            f"Got pair ({p.i},{p.j})."
        )

    # Compute / reuse the deterministic centered-growth layout.
    # layout depends only on width, not on n.
    layout = layout if layout is not None else centered_growth_layout(width)

    # Another sanity check: width argument must match the layout.
    if layout.width != width:
        raise ValueError(f"layout.width={layout.width} does not match width={width}")

    terms: List[Dict] = []

    # -----------------------------------------------------------------
    # (A) Baseline ZZ on all grid edges of G_n
    # -----------------------------------------------------------------
    # Each edge coefficient is deterministic per (u,v), independent of n.
    # We deliberately include *all* grid edges (not only those touching 0 or 1)
    # to make the prior look like a realistic 2-local background.
    for (u, v) in grid_edges_for_n(n, layout):
        g = rng(p.seed, "J", u, v)
        Jij = float(p.J0) + float(p.sigma_J) * float(g.normal())
        terms.append({"c": clamp_nonzero(Jij), "z": [int(u), int(v)]})

    # -----------------------------------------------------------------
    # Compute σ3 relative to J01 (the baseline ZZ on (0,1))
    # -----------------------------------------------------------------
    # IMPORTANT:
    #   We always define the residue scale relative to the diagnostic coupling.
    #   This makes eta3 interpretable: "how large is leakage compared to the
    #   intended (0,1) interaction scale?"
    g01 = rng(p.seed, "J", 0, 1)
    J01 = float(p.J0) + float(p.sigma_J) * float(g01.normal())
    J01 = clamp_nonzero(J01)
    sigma3 = abs(J01) * float(p.eta3)

    # -----------------------------------------------------------------
    # (B) Residue: Z_0 Z_1 Z_k for k in radius-r neighborhood
    # -----------------------------------------------------------------
    r = radius_of_n(n, p)
    cand = spectator_candidates(n, layout, 0, 1, r)

    for (k, dk) in cand:
        pk = p_on(dk, p)
        if pk <= 0.0:
            continue

        # On/off is deterministic per (seed, 0, 1, k).
        gu = rng(p.seed, "on3", 0, 1, k)
        if float(gu.random()) >= pk:
            continue

        # Coefficient is deterministic per (seed, 0, 1, k).
        ge = rng(p.seed, "eps3", 0, 1, k)
        eps = float(sigma3) * float(ge.normal())
        terms.append({"c": clamp_nonzero(eps), "z": [0, 1, int(k)]})

    return terms


def build_yaml_spec(
    n: int,
    width: int,
    p: FamilyParams,
    layout: Optional[CenteredGrowthLayout] = None,
) -> Dict:
    """Build the YAML dictionary in the project schema.

    We emit exactly the required fields for `model_provider.py`:

      version: "0.1"
      n: <int>
      bit_order: "lsb"
      diagonal_components:
        source: "analytic"
        analytic:
          kind: "pauli_z_sum"
          terms: [...]
        explicit: null

    Additionally, we include a small `family_meta` block.
    ModelProvider ignores unknown keys; meta is useful for humans.
    """

    layout = layout if layout is not None else centered_growth_layout(width)
    a_xy, b_xy = layout.anchor_xy

    return {
        "version": "0.1",
        "n": int(n),
        "bit_order": "lsb",
        "family_meta": {
            "family": "grid_radius_r_centered_growth_v2",
            "grid_width": int(width),
            "indexing": "centered-growth / BFS-shell around logical edge (0,1)",
            "tie_break": "sort by (dist, y, x)",
            "anchor_edge_xy": [[int(a_xy[0]), int(a_xy[1])], [int(b_xy[0]), int(b_xy[1])]],
            "note": "(0,1) is placed near grid center; G_n is prefix-induced in this order",
        },
        "diagonal_components": {
            "source": "analytic",
            "analytic": {
                "kind": "pauli_z_sum",
                "terms": build_terms_for_n(n, width, p, layout=layout),
            },
            "explicit": None,
        },
    }


def write_yaml(path: Path, spec: Dict) -> None:
    """Write a YAML file with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(spec, f, sort_keys=False, default_flow_style=False)


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Generate diagonal_model.yaml files for the simulation prior: "
            "2D grid (sparse) + radius-r spectator rule + centered-growth (BFS-shell) indexing."
        )
    )

    ap.add_argument("--out-dir", type=str, default="models_grid_BFS_Shell", help="Directory to write YAML files")
    ap.add_argument("--n-min", type=int, default=2, help="Minimum n (inclusive)")
    ap.add_argument("--n-max", type=int, default=7, help="Maximum n (inclusive)")

    # Grid width fixed for the whole sweep (prefix stability!)
    ap.add_argument(
        "--grid-width",
        type=int,
        default=None,
        help=(
            "Fixed grid width W. If omitted, uses ceil(sqrt(n_max)). "
            "Requirement: W>=2 and W^2 >= n_max."
        ),
    )

    ap.add_argument("--seed", type=int, default=12345)

    # We keep --pair for compatibility with older scripts/CLIs,
    # but in this centered-growth file we REQUIRE it to be 0,1.
    ap.add_argument(
        "--pair",
        type=str,
        default="0,1",
        help='Diagnostic pair as "i,j". NOTE: centered-growth indexing assumes (0,1).',
    )

    # Baseline 2-local knobs
    ap.add_argument("--J0", type=float, default=0.25)
    ap.add_argument("--sigma-J", type=float, default=0.00)

    # Residue knobs
    ap.add_argument("--eta3", type=float, default=0.20)
    ap.add_argument("--lambda3", type=float, default=0.8)
    ap.add_argument("--alpha-dist", type=float, default=1.0)

    # Radius schedule knobs
    ap.add_argument("--radius-rule", type=str, default="log2", choices=["fixed", "log2", "loglog2"])
    ap.add_argument("--radius-fixed", type=int, default=1)
    ap.add_argument("--radius-cap", type=int, default=999)

    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.n_min < 2 or args.n_max < args.n_min:
        raise SystemExit("Invalid n range: require 2 <= n_min <= n_max")

    # -----------------------------------------------------------------
    # Choose W once using n_max (prefix stability across n)
    # -----------------------------------------------------------------
    if args.grid_width is None:
        width = int(math.ceil(math.sqrt(args.n_max)))
        width = max(2, width)
    else:
        width = int(args.grid_width)
        if width < 2:
            raise SystemExit("grid-width must be >= 2")

    if width * width < int(args.n_max):
        raise SystemExit(
            f"grid-width={width} too small for n_max={args.n_max}. "
            "Need width^2 >= n_max for a W×W grid."
        )

    # -----------------------------------------------------------------
    # Parse and validate diagnostic pair
    # -----------------------------------------------------------------
    try:
        i_str, j_str = args.pair.split(",")
        i, j = int(i_str.strip()), int(j_str.strip())
    except Exception:
        raise SystemExit('Invalid --pair. Expected "i,j", e.g. --pair 0,1')

    i, j = (i, j) if i < j else (j, i)
    if (i, j) != (0, 1):
        raise SystemExit(
            "This script uses centered-growth indexing around the diagnostic edge (0,1). "
            f"Please use --pair 0,1 (got {args.pair!r})."
        )

    # Bundle parameters
    p = FamilyParams(
        seed=int(args.seed),
        i=i,
        j=j,
        J0=float(args.J0),
        sigma_J=float(args.sigma_J),
        eta3=float(args.eta3),
        lambda3=float(args.lambda3),
        alpha_dist=float(args.alpha_dist),
        radius_rule=str(args.radius_rule),
        radius_fixed=int(args.radius_fixed),
        radius_cap=int(args.radius_cap),
    )

    # Precompute the deterministic centered-growth layout once.
    layout = centered_growth_layout(width)
    a_xy, b_xy = layout.anchor_xy
    print(f"[centered-growth] grid_width={width}, anchor_edge_xy={a_xy}-{b_xy}")

    # Emit YAMLs
    out_dir = Path(args.out_dir)
    for n in range(int(args.n_min), int(args.n_max) + 1):
        spec = build_yaml_spec(n, width, p, layout=layout)
        out_path = out_dir / f"diagonal_model_grid_BFS_Shell_n{n}.yaml"
        write_yaml(out_path, spec)
        print(f"Wrote {out_path}  (r(n)={radius_of_n(n, p)})")


if __name__ == "__main__":
    main()