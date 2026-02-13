#!/usr/bin/env python3
"""
qiskit_runner.py  (κ‑litmus)

Why this file exists
--------------------
κ‑litmus is a *quantum circuit multimeter*: it is **not** trying to reconstruct an unknown
n‑qubit unitary (no tomography / GST). Instead it targets a specific structure class
(**Z‑diagonal / near‑diagonal unitary blocks**, e.g. QAOA cost layers and their compiled
variants) and diagnoses them via *plaquette curvatures* κ₍ᵢⱼ₎(z_rest).

This runner is the bridge from the theory/protocol specs to something you can execute
with Qiskit in three regimes:

  1) **statevector**   — exact, deterministic reference (debug / validation)
  2) **fake_backend**  — noisy rehearsal using Aer + a noise model derived from a frozen
                         backend snapshot JSON
  3) **qpu**           — real IBM hardware execution using qiskit-ibm-runtime SamplerV2
                         (job mode)

What it produces is a **schema‑stable, bootstrap‑friendly dataset**:
- per (context, setting) raw 1‑bit counts (counts.json)
- per context reconstructed κ̂ plus phasor quality metrics (kappa_results.csv)
- full provenance (run_meta.json): hashes, versions, cache keys, job ids, warnings

This strictness is intentional: downstream κ‑litmus analysis assumes these schemas and
conventions are stable across runs and across modes.

Inputs / contracts (do not invent new YAML keys)
------------------------------------------------
See: qiskit_runner_work_instruction_v2.md

* qiskit_runner.yaml
    - “run intent”: which model/backend/mode/shots, which (i,j) pair, which contexts
    - “safety rails”: fail-fast if conventions mismatch (θ sign, bit order, mapping)
    - reproducibility knobs: fixed transpiler seed/level, optional circuit freezing (.qpy)

* diagonal_model_*.yaml
    - defines U = Π_S exp(+i c_S Z_S) as analytic pauli_z_sum terms
    - may include hardware_meta.physical_qubits (logical→physical mapping)
      required in fake_backend/qpu so that the diagnostic pair lives on the intended chip edge

* backend_snapshot_json
    - frozen snapshot of an IBM backend (connectivity, basis, readout properties, limits, …)
    - used for: fake_backend noise model + transpile constraints + mismatch checks

Protocol B recap (phasor form)
------------------------------
For each context z_rest_int and logical pair (i,j) with i<j, define the four face vertices:

  z00 = z_base
  z10 = z_base ^ (1<<i)
  z01 = z_base ^ (1<<j)
  z11 = z_base ^ (1<<i) ^ (1<<j)

where z_base is built by inserting the (n−2) context bits into all qubit positions except i,j,
leaving i=j=0. (This bit‑insertion rule MUST match sim_runner.py.)

Define:

  a = φ(z00) − φ(z01)
  b = φ(z10) − φ(z11)
  κ = angle(exp(i(a−b)))

Protocol B measures four expectation values (ideally):

  m1 = cos(a)
  m2 = sin(a)
  m3 = cos(b)
  m4 = sin(b)

Reconstruction:

  u_a = m1 + i m2
  u_b = m3 + i m4
  κ̂  = angle(u_a * conj(u_b))

Quality metrics (very useful on hardware):

  amp_a = |u_a|,  amp_b = |u_b|

Design choices that matter in code review
-----------------------------------------
* **Fail‑closed config:** YAML is treated as a contract. Unknown keys raise errors.
  Optional toggles are CLI flags and are recorded into run_meta.json.

* **Bit order:** project convention is “lsb” (qubit 0 is the least significant bit in z).
  We explicitly handle bit operations accordingly and validate model_yaml.bit_order.

* **θ rule:** model uses exp(+i c Z_S), Qiskit uses RZ(θ)=exp(−i θ/2 Z), so θ = −2c.
  Wrong sign ⇒ wrong κ sign.

* **Measure only qubit j:** each circuit measures a single classical bit in a register named “meas”.
  This avoids fragile multi-bit marginalization.

* **Reproducibility & freeze:** transpilation is stochastic. We pin seeds and optionally freeze
  transpiled circuits as QPY artifacts so fake_backend and qpu can execute the *same* circuits.

This file is intentionally self‑contained and does not add new YAML keys.
If you need new behavior, prefer a CLI flag (recorded in meta) over extending the YAML schema.
"""

from __future__ import annotations

import argparse
import cmath
import csv
import dataclasses
import hashlib
import importlib.metadata as importlib_metadata
import json
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _json_default(obj: Any) -> Any:
    """JSON serialization helper for non-standard types."""
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ----------------------------
# Project-local dependency
# ----------------------------
try:
    from model_provider import ModelProvider, ModelProviderError
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "Failed to import model_provider.py (project-local). "
        "Make sure qiskit_runner.py is executed in the same directory/module context as model_provider.py."
    ) from e


# ----------------------------
# Optional Qiskit imports
# ----------------------------
_QISKIT_IMPORT_ERROR: Optional[BaseException] = None
try:
    from qiskit import ClassicalRegister, QuantumCircuit, transpile, qpy
    from qiskit.transpiler import CouplingMap
    from qiskit.quantum_info import Statevector
except Exception as e:  # pragma: no cover
    _QISKIT_IMPORT_ERROR = e
    ClassicalRegister = None  # type: ignore
    QuantumCircuit = None  # type: ignore
    transpile = None  # type: ignore
    qpy = None  # type: ignore
    CouplingMap = None  # type: ignore
    Statevector = None  # type: ignore


_AER_IMPORT_ERROR: Optional[BaseException] = None
try:
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error
except Exception as e:  # pragma: no cover
    _AER_IMPORT_ERROR = e
    AerSimulator = None  # type: ignore
    NoiseModel = None  # type: ignore
    ReadoutError = None  # type: ignore
    depolarizing_error = None  # type: ignore


_IBM_IMPORT_ERROR: Optional[BaseException] = None
try:
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2
except Exception as e:  # pragma: no cover
    _IBM_IMPORT_ERROR = e
    QiskitRuntimeService = None  # type: ignore
    SamplerV2 = None  # type: ignore

# least_busy was removed in newer qiskit-ibm-runtime versions
# We implement it manually if not available
_least_busy_available = False
try:
    from qiskit_ibm_runtime import least_busy
    _least_busy_available = True
except ImportError:
    least_busy = None  # type: ignore


# =============================================================================
# Errors
# =============================================================================

class RunnerError(RuntimeError):
    """Base runner error."""


class ConfigError(RunnerError):
    """Bad config YAML."""


class PolicyError(RunnerError):
    """Policy mismatch (fail-fast)."""


class SnapshotError(RunnerError):
    """Invalid backend snapshot JSON."""


class ExecutionError(RunnerError):
    """Execution failure (QPU / simulator)."""


# =============================================================================
# Small utilities
# =============================================================================

# Design note:
#   These are intentionally tiny / dependency-free helpers that are used across modes.
#   In particular, the bit-manipulation helpers (unpack_z_rest, face_vertices) are duplicated
#   here (instead of imported from sim_runner.py) so that this file stays self-contained,
#   but they MUST remain consistent with sim_runner.py and the formal spec.

SETTINGS: Tuple[str, str, str, str] = ("cos_a", "sin_a", "cos_b", "sin_b")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(obj: Any) -> str:
    """Stable JSON encoding for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def wrap_to_pi(x: float) -> float:
    """Wrap angle to (-π, π]."""
    w = math.fmod(x + math.pi, 2 * math.pi)
    if w <= 0:
        w += 2 * math.pi
    return w - math.pi


def angle_of(z: complex) -> float:
    """Angle in (-π, π]."""
    return wrap_to_pi(math.atan2(z.imag, z.real))


def sorted_pair(i: int, j: int) -> Tuple[int, int]:
    if i == j:
        raise ValueError("pair must contain two distinct indices")
    return (i, j) if i < j else (j, i)


def normalize_protocol_pairs(pair_field: Any) -> List[Tuple[int, int]]:
    """Normalize the YAML field ``protocol.pair`` into a list of canonical pairs.

    Why this exists
    ---------------
    The original κ‑litmus runner assumed *one* diagnostic pair per run/job.
    That is convenient, but on real hardware a reviewer can complain that a
    "signal pair" and a "control pair" were executed in different Runtime jobs
    (hence different drift conditions).

    To address this without inventing new YAML keys we support **two shapes**:

      1) Legacy (single pair):
            protocol:
              pair: [0, 1]

      2) New (multi‑pair in the same run/job):
            protocol:
              pair: [[0, 1], [2, 3]]

    This function:
      - converts either shape into ``[(i,j), (k,l), ...]``
      - sorts each pair so i<j (κ_{ij} is an unordered pair invariant)
      - rejects duplicates after sorting (to avoid accidental double‑sampling)

    Note: we *do not* range‑check against n here (that happens later, once the
    model's n is known).
    """

    # Accept list/tuple for robustness; YAML usually gives list.
    if isinstance(pair_field, (list, tuple)) and len(pair_field) == 2 and all(isinstance(x, int) for x in pair_field):
        raw_pairs = [pair_field]
    elif isinstance(pair_field, list) and pair_field and all(
        isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(x, int) for x in p) for p in pair_field
    ):
        raw_pairs = pair_field
    else:
        raise ConfigError(
            "protocol.pair must be either [i,j] (legacy single pair) or [[i,j],[k,l],...] (multi-pair), "
            f"got {pair_field!r}"
        )

    out: List[Tuple[int, int]] = []
    seen: set = set()
    for p in raw_pairs:
        i, j = sorted_pair(int(p[0]), int(p[1]))
        if (i, j) in seen:
            raise ConfigError(
                "Duplicate pair detected in protocol.pair after canonicalization: "
                f"{(i, j)}. Remove duplicates to avoid double-sampling."
            )
        seen.add((i, j))
        out.append((i, j))

    return out


def rest_positions(n: int, i: int, j: int) -> List[int]:
    i, j = sorted_pair(i, j)
    return [k for k in range(n) if k not in (i, j)]


# Context encoding helper (MUST match sim_runner.py)
# ------------------------------------------------
# z_rest_int is the integer encoding of the (n-2) "spectator" bits (all qubits except i and j).
# We insert those bits into the full n-bit computational-basis index z according to:
#   - bit t of z_rest_int goes to qubit rest_positions[t]
#   - rest_positions is the ascending list of qubit indices excluding {i,j}
# Bits i and j are left as 0 here; toggling them later generates the 4 face vertices.

def unpack_z_rest(z_rest_int: int, n: int, i: int, j: int) -> int:
    """Build z_base from z_rest_int by inserting context bits into full z_int. (Matches sim_runner)"""
    i, j = sorted_pair(i, j)
    rest = rest_positions(n, i, j)
    width = n - 2
    if z_rest_int < 0 or z_rest_int >= (1 << width):
        raise ValueError(f"z_rest_int out of range for n={n}: {z_rest_int}")
    z_base = 0
    for t, k in enumerate(rest):
        bit = (z_rest_int >> t) & 1
        if bit:
            z_base |= 1 << k
    return z_base


# Face vertex ordering helper (MUST match sim_runner.py)
# ----------------------------------------------------
# For a fixed pair (i,j) and context z_rest_int, κ-litmus treats the {i,j} face of the
# n-dimensional hypercube. The ordering returned here is significant:
#   (z00, z10, z01, z11) corresponds to bits (i,j) = (0,0), (1,0), (0,1), (1,1).
# This ordering is used consistently for:
#   a = φ(z00) - φ(z01)
#   b = φ(z10) - φ(z11)
#   κ = wrap_to_pi(a - b)

def face_vertices(z_rest_int: int, n: int, i: int, j: int) -> Tuple[int, int, int, int]:
    """Return (z00, z10, z01, z11) for the (i,j) face at context z_rest_int. (Matches sim_runner)"""
    i, j = sorted_pair(i, j)
    z_base = unpack_z_rest(z_rest_int, n, i, j)
    z00 = z_base
    z10 = z_base ^ (1 << i)
    z01 = z_base ^ (1 << j)
    z11 = z_base ^ (1 << i) ^ (1 << j)
    return z00, z10, z01, z11


def get_pkg_versions() -> Dict[str, str]:
    """Collect dependency versions for provenance. Missing packages are reported as 'not_installed'."""
    pkgs = ["qiskit", "qiskit-aer", "qiskit-ibm-runtime", "numpy", "pyyaml"]
    out: Dict[str, str] = {}
    for p in pkgs:
        try:
            out[p] = importlib_metadata.version(p)
        except Exception:
            out[p] = "not_installed"
    return out


def resolve_path(base_dir: Path, maybe_rel: str) -> Path:
    p = Path(maybe_rel)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def ensure_qiskit_available() -> None:
    if _QISKIT_IMPORT_ERROR is not None:
        raise RunnerError(
            "Qiskit is required but could not be imported. "
            "Install at least 'qiskit' (and optionally 'qiskit-aer', 'qiskit-ibm-runtime').\n"
            f"Import error: {_QISKIT_IMPORT_ERROR}"
        )


def ensure_aer_available() -> None:
    ensure_qiskit_available()
    if _AER_IMPORT_ERROR is not None:
        raise RunnerError(
            "fake_backend mode requires qiskit-aer, but it could not be imported.\n"
            f"Import error: {_AER_IMPORT_ERROR}"
        )


def ensure_ibm_runtime_available() -> None:
    ensure_qiskit_available()
    if _IBM_IMPORT_ERROR is not None:
        raise RunnerError(
            "qpu mode requires qiskit-ibm-runtime, but it could not be imported.\n"
            f"Import error: {_IBM_IMPORT_ERROR}"
        )

# IBM Runtime service construction
# -------------------------------
# We keep this as a tiny wrapper so that:
#   - the runner can be used in environments with saved credentials (no explicit token here)
#   - we only pass through *documented* YAML keys (channel/instance/plans_preference)
#   - any "plan preference" logic is best-effort and safely ignorable if Runtime APIs differ

def create_ibm_service(ibm_cfg: Dict[str, Any]) -> "QiskitRuntimeService":
    """
    Create a QiskitRuntimeService using only provided (non-null) kwargs.

    Config contract note:
    - qiskit_runner.yaml uses ibm.instance and may include ibm.plans_preference.
    - We do NOT invent new YAML keys; plans_preference is best-effort (may be ignored if unsupported).
    """
    ensure_ibm_runtime_available()
    assert QiskitRuntimeService is not None

    kwargs: Dict[str, Any] = {}
    # 'channel' is optional (some setups rely on saved account defaults)
    if isinstance(ibm_cfg.get("channel"), str) and ibm_cfg.get("channel"):
        kwargs["channel"] = ibm_cfg.get("channel")
    if ibm_cfg.get("instance") is not None:
        kwargs["instance"] = ibm_cfg.get("instance")

    # Best-effort: if instance not specified but plans_preference exists, try to pick an instance
    # whose path contains "/<plan>/" (e.g., "/open/"). If the installed runtime doesn't expose
    # instances(), we simply fall back to default account instance.
    plans = ibm_cfg.get("plans_preference")
    if (kwargs.get("instance") is None) and isinstance(plans, list) and plans:
        try:
            tmp = QiskitRuntimeService(**{k: v for k, v in kwargs.items() if k != "instance"})
            if hasattr(tmp, "instances"):
                insts = list(tmp.instances())  # type: ignore[attr-defined]
                for plan in plans:
                    if not isinstance(plan, str):
                        continue
                    token = f"/{plan.strip('/')}/"
                    for inst in insts:
                        if token in str(inst):
                            kwargs["instance"] = str(inst)
                            break
                    if "instance" in kwargs:
                        break
        except Exception:
            pass

    return QiskitRuntimeService(**kwargs)



# =============================================================================
# Config loading + validation
# =============================================================================

# Design note:
#   qiskit_runner.yaml is treated as a *contract*, not a suggestion.
#   We reject unknown keys to prevent silent typos and config/schema drift.
#   If you need experimental toggles, prefer CLI flags (and record them in run_meta.json).

ALLOWED_TOP_KEYS = {
    "version",
    "model_yaml",
    "backend_snapshot_json",
    "mode",
    "shots",
    "seed",
    "ibm",
    "backend",
    "compile",
    "protocol",
    "policies",
    "job",
    "output",
}


def _require_keys(d: Dict[str, Any], keys: Sequence[str], where: str) -> None:
    for k in keys:
        if k not in d:
            raise ConfigError(f"Missing required key {k!r} in {where}")


def _reject_unknown_keys(d: Dict[str, Any], allowed: set, where: str) -> None:
    extra = set(d.keys()) - set(allowed)
    if extra:
        raise ConfigError(f"Unknown keys in {where}: {sorted(extra)} (do not invent new keys)")


# Config loader (fail-closed / schema-stable)
# ------------------------------------------
# The runner YAML is shared across multiple tools (sim_runner, qiskit_runner, analysis scripts).
# To avoid subtle, hard-to-debug failures we:
#   - reject unknown keys at every nested level ("do not invent new keys")
#   - validate types/enums for every field we consume
#   - keep optional toggles out of YAML (use CLI flags instead)
# This makes code review and future maintenance much safer.

def load_config(config_path: Path) -> Dict[str, Any]:
    """Load and validate qiskit_runner.yaml."""
    try:
        import yaml  # local import to keep hard deps minimal
    except Exception as e:  # pragma: no cover
        raise RunnerError("pyyaml is required to read qiskit_runner.yaml") from e

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Config YAML must parse to a mapping/dict.")

    _reject_unknown_keys(raw, ALLOWED_TOP_KEYS, where="root")

    _require_keys(raw, ["version", "model_yaml", "backend_snapshot_json", "mode", "shots", "ibm", "backend", "compile", "protocol", "policies", "job", "output"], "root")

    # Basic structure checks (only keys; deeper semantic checks happen later)
    if raw["mode"] not in ("statevector", "fake_backend", "qpu"):
        raise ConfigError(f"Unsupported mode: {raw['mode']!r} (expected statevector|fake_backend|qpu)")

    if not isinstance(raw["shots"], int) or raw["shots"] <= 0:
        raise ConfigError(f"shots must be a positive int, got {raw['shots']!r}")

    # Nested unknown key checks
    _reject_unknown_keys(raw["ibm"], {"channel", "instance", "plans_preference"}, where="ibm")
    _reject_unknown_keys(raw["backend"], {"name", "auto_policy", "require_operational", "min_num_qubits"}, where="backend")
    _reject_unknown_keys(raw["compile"], {"optimization_level", "seed_transpiler", "layout", "routing_method"}, where="compile")
    _reject_unknown_keys(raw["compile"]["layout"], {"policy"}, where="compile.layout")
    _reject_unknown_keys(raw["protocol"], {"name", "pair", "context"}, where="protocol")
    _reject_unknown_keys(raw["protocol"]["context"], {"mode", "samples", "seed"}, where="protocol.context")
    _reject_unknown_keys(
        raw["policies"],
        {"theta_rule", "require_bit_order", "require_physical_mapping", "model_backend_mismatch", "freeze_transpiled_circuits", "reuse_frozen_circuits"},
        where="policies",
    )
    _reject_unknown_keys(raw["policies"]["require_physical_mapping"], {"when_mode_in"}, where="policies.require_physical_mapping")
    _reject_unknown_keys(raw["policies"]["reuse_frozen_circuits"], {"when_mode_in"}, where="policies.reuse_frozen_circuits")
    _reject_unknown_keys(raw["job"], {"auto_split", "max_circuits_per_job", "max_executions_per_job"}, where="job")
    _reject_unknown_keys(raw["output"], {"dir", "run_id", "kappa_file", "counts_file", "meta_file", "circuits_dir"}, where="output")

    # Protocol identity
    if raw["protocol"]["name"] != "protocol_b":
        raise ConfigError("Currently only protocol.name == 'protocol_b' is supported.")

    # protocol.pair (backward compatible)
    # -------------------------------
    # Historically κ‑litmus used a single diagnostic pair:
    #     pair: [i, j]
    #
    # Reviewer/reproducibility concern: if you run a "signal pair" and a "control pair"
    # in *separate* IBM Runtime jobs, a reviewer can reasonably complain that they were
    # not executed under comparable drift/conditions.
    #
    # Therefore we also support a *multi‑pair* run with the SAME YAML key:
    #     pair: [[i, j], [k, l], ...]
    #
    # This change is intentionally minimal:
    #   - we do NOT invent a new YAML key
    #   - the legacy shape [i,j] still works unchanged
    #   - the range check (0 <= index < n) happens later, after model n is known
    pair_field = raw["protocol"]["pair"]

    def _is_pair_2int(obj: Any) -> bool:
        return (
            isinstance(obj, (list, tuple))
            and len(obj) == 2
            and isinstance(obj[0], int)
            and isinstance(obj[1], int)
        )

    if _is_pair_2int(pair_field):
        # legacy: [i,j]
        pass
    elif isinstance(pair_field, list) and pair_field and all(_is_pair_2int(p) for p in pair_field):
        # new: [[i,j],[k,l],...]
        pass
    else:
        raise ConfigError(
            "protocol.pair must be either [i,j] (legacy single pair) or "
            "[[i,j],[k,l],...] (multi-pair), got "
            f"{pair_field!r}"
        )

    ctx = raw["protocol"]["context"]
    if ctx["mode"] not in ("exhaustive", "sample"):
        raise ConfigError(f"protocol.context.mode must be 'exhaustive' or 'sample', got {ctx['mode']!r}")
    if ctx["mode"] == "sample":
        if not isinstance(ctx.get("samples"), int) or int(ctx["samples"]) <= 0:
            raise ConfigError("protocol.context.samples must be positive int when mode=='sample'")
        if not isinstance(ctx.get("seed"), int):
            raise ConfigError("protocol.context.seed must be int when mode=='sample'")

    # Policies
    if raw["policies"]["theta_rule"] != "-2c":
        raise PolicyError("This runner implements only theta_rule == '-2c' (fail-fast).")
    # Bit order safety rail (HIGH-RISK if wrong)
    # ---------------------------------------
    # κ‑litmus uses an integer z ∈ {0,1}^n to label computational basis states |z⟩.
    # Throughout this project we adopt Qiskit's common convention:
    #   - qubit 0 is the *least significant bit* (LSB) of the basis index
    #   - i.e., (idx >> q) & 1 extracts z_q
    # Many helper functions below (unpack_z_rest, statevector ordering, face vertex
    # construction, etc.) are implemented under this assumption.
    #
    # IMPORTANT: allowing 'msb' to pass config validation would create a
    # 'passes validation but produces wrong answers' footgun. We therefore
    # enforce lsb-only here (fail-fast).
    if raw["policies"]["require_bit_order"] != "lsb":
        raise PolicyError("policies.require_bit_order must be 'lsb' (msb is not supported by this runner)")

    if raw["policies"]["model_backend_mismatch"] not in ("fail", "warn"):
        raise PolicyError("policies.model_backend_mismatch must be 'fail' or 'warn'")

    # Compile
    if raw["compile"]["layout"]["policy"] not in ("from_model", "automatic"):
        raise ConfigError("compile.layout.policy must be 'from_model' or 'automatic'")
    if raw["compile"]["routing_method"] not in ("sabre", "basic", "none"):
        raise ConfigError("compile.routing_method must be 'sabre' | 'basic' | 'none'")
    if not isinstance(raw["compile"]["optimization_level"], int) or raw["compile"]["optimization_level"] not in (0, 1, 2, 3):
        raise ConfigError("compile.optimization_level must be int in {0,1,2,3}")
    if not isinstance(raw["compile"]["seed_transpiler"], int):
        raise ConfigError("compile.seed_transpiler must be int")

    # Job
    if not isinstance(raw["job"]["max_circuits_per_job"], int) or raw["job"]["max_circuits_per_job"] <= 0:
        raise ConfigError("job.max_circuits_per_job must be positive int")
    if not isinstance(raw["job"]["max_executions_per_job"], int) or raw["job"]["max_executions_per_job"] <= 0:
        raise ConfigError("job.max_executions_per_job must be positive int")

    # Output
    if raw["output"]["run_id"] is None:
        raise ConfigError("output.run_id must be 'auto' or a string (not null)")
    if raw["output"]["circuits_dir"] is None:
        # Allowed: null to disable artifacts
        pass
    else:
        if not isinstance(raw["output"]["circuits_dir"], str):
            raise ConfigError("output.circuits_dir must be a string or null")

    return raw


# =============================================================================
# Snapshot parsing (minimal, robust)
# =============================================================================

# Snapshot note:
#   For reproducibility we consume a *frozen backend snapshot JSON* produced by this project.
#   We do NOT rely on a live Backend object for fake_backend rehearsals.
#   The parser is intentionally minimal (only the fields we need) and tolerant to missing/unknown
#   entries so that new snapshot fields do not break old runners.

def _val(x: Any) -> Optional[float]:
    """Extract numeric value from snapshot property entry."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, dict) and "value" in x and isinstance(x["value"], (int, float)):
        return float(x["value"])
    return None


@dataclass
class BackendSnapshot:
    backend_name: str
    num_qubits: int
    coupling_map: List[List[int]]
    basis_gates: List[str]
    properties: Dict[str, Any]
    configuration: Dict[str, Any]
    gate_properties: Dict[str, Any]
    retrieved_at: Optional[str] = None

    @staticmethod
    def load(path: Path) -> "BackendSnapshot":
        raw = json.loads(path.read_text(encoding="utf-8"))
        for k in ("backend_name", "num_qubits", "coupling_map", "basis_gates", "gate_properties", "properties", "configuration"):
            if k not in raw:
                raise SnapshotError(f"backend_snapshot_json missing required key: {k!r}")
        if not isinstance(raw["coupling_map"], list) or not all(isinstance(e, list) and len(e) == 2 for e in raw["coupling_map"]):
            raise SnapshotError("snapshot.coupling_map must be list of [u,v] edges")
        if not isinstance(raw["basis_gates"], list) or not all(isinstance(g, str) for g in raw["basis_gates"]):
            raise SnapshotError("snapshot.basis_gates must be list[str]")
        return BackendSnapshot(
            backend_name=str(raw["backend_name"]),
            num_qubits=int(raw["num_qubits"]),
            coupling_map=[[int(u), int(v)] for (u, v) in raw["coupling_map"]],
            basis_gates=[str(g) for g in raw["basis_gates"]],
            properties=raw["properties"],
            configuration=raw["configuration"],
            gate_properties=raw["gate_properties"],
            retrieved_at=raw.get("retrieved_at"),
        )

    def max_experiments(self) -> Optional[int]:
        v = self.configuration.get("max_experiments")
        return int(v) if isinstance(v, int) else None

    def max_shots(self) -> Optional[int]:
        v = self.configuration.get("max_shots")
        return int(v) if isinstance(v, int) else None

    def readout_error_for_qubit(self, q: int) -> Optional[Tuple[float, float]]:
        """
        Return (p10, p01) where:
          p10 = P(meas=1 | prep=0)  (prob_meas1_prep0)
          p01 = P(meas=0 | prep=1)  (prob_meas0_prep1)
        """
        try:
            qprops = self.properties["qubits"][q]
        except Exception:
            return None
        p10 = _val(qprops.get("prob_meas1_prep0"))
        p01 = _val(qprops.get("prob_meas0_prep1"))
        if p10 is None or p01 is None:
            return None
        # Clamp to [0,1]
        p10 = max(0.0, min(1.0, float(p10)))
        p01 = max(0.0, min(1.0, float(p01)))
        return (p10, p01)



def filter_basis_gates(basis_gates: Sequence[str]) -> List[str]:
    """
    Backend snapshots sometimes include control-flow op names (e.g., 'if_else') in basis_gates.
    Qiskit's transpiler / AerSimulator may not accept those in the basis gate list.
    We conservatively drop known control-flow tokens and keep everything else.
    """
    drop = {"if_else", "for_loop", "while_loop", "switch_case", "box"}
    out: List[str] = []
    for g in basis_gates:
        if not isinstance(g, str):
            continue
        if g in drop:
            continue
        out.append(g)
    return out

# =============================================================================
# Model parsing helpers (YAML)
# =============================================================================

# Model YAML note:
#   We instantiate ModelProvider (Module 1) as the source of truth for φ(z) evaluation,
#   but we also parse the model YAML directly to extract runner-level metadata:
#     - hardware_meta.backend (for mismatch checks)
#     - hardware_meta.physical_qubits (for pinning logical→physical mapping)
#   This separation keeps physics (φ) and runner policy (mapping/reproducibility) conceptually clean.

@dataclass
class ModelInfo:
    n: int
    bit_order: str
    hardware_backend: Optional[str]
    physical_qubits: Optional[List[int]]
    terms: List[Dict[str, Any]]  # raw analytic terms


def load_model_info(model_yaml_path: Path) -> ModelInfo:
    try:
        import yaml
    except Exception as e:  # pragma: no cover
        raise RunnerError("pyyaml is required to read model YAML") from e

    spec = yaml.safe_load(model_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise RunnerError("Model YAML must be a mapping/dict.")
    for k in ("n", "bit_order", "diagonal_components"):
        if k not in spec:
            raise RunnerError(f"Model YAML missing required key: {k!r}")

    n = int(spec["n"])
    bit_order = str(spec["bit_order"])
    dc = spec["diagonal_components"]
    if not isinstance(dc, dict) or dc.get("source") != "analytic":
        raise RunnerError("Only diagonal_components.source == 'analytic' is supported.")
    analytic = dc.get("analytic")
    if not isinstance(analytic, dict) or analytic.get("kind") != "pauli_z_sum":
        raise RunnerError("Only analytic.kind == 'pauli_z_sum' is supported.")
    terms = analytic.get("terms")
    if not isinstance(terms, list):
        raise RunnerError("analytic.terms must be a list")

    hw = spec.get("hardware_meta") if isinstance(spec.get("hardware_meta"), dict) else None
    hw_backend = None
    physical = None
    if hw:
        if isinstance(hw.get("backend"), str):
            hw_backend = hw["backend"]
        if isinstance(hw.get("physical_qubits"), list):
            physical = [int(x) for x in hw["physical_qubits"]]

    return ModelInfo(
        n=n,
        bit_order=bit_order,
        hardware_backend=hw_backend,
        physical_qubits=physical,
        terms=terms,
    )


def validate_physical_mapping(physical_qubits: List[int], n: int, snapshot: BackendSnapshot) -> None:
    if len(physical_qubits) != n:
        raise PolicyError(f"hardware_meta.physical_qubits length {len(physical_qubits)} != n {n}")
    if len(set(physical_qubits)) != len(physical_qubits):
        raise PolicyError("hardware_meta.physical_qubits contains duplicates")
    for q in physical_qubits:
        if q < 0 or q >= snapshot.num_qubits:
            raise PolicyError(f"hardware_meta.physical_qubits contains out-of-range qubit id {q} (num_qubits={snapshot.num_qubits})")


# =============================================================================
# Term canonicalization + diagonal circuit synthesis
# =============================================================================

# Synthesis note:
#   diagonal_model.yaml terms are meant to represent:
#       U = Π_S exp(+i c_S Z_S)
#   but YAML generation can leave supports unsorted or repeated across terms.
#   We canonicalize supports and merge duplicates to make synthesis deterministic and cache-friendly.
#   Global-phase terms are dropped because κ is gauge-invariant to them.

def canonicalize_terms(raw_terms: List[Dict[str, Any]], n: int) -> List[Tuple[Tuple[int, ...], float]]:
    """
    Canonicalize terms:
    - sort support list
    - reject duplicates in support
    - merge identical supports (sum c)
    - drop empty support (global phase)
    """
    accum: Dict[Tuple[int, ...], float] = {}
    for t_idx, term in enumerate(raw_terms):
        if not isinstance(term, dict) or "c" not in term or "z" not in term:
            raise RunnerError(f"Invalid term at index {t_idx}: expected {{'c':..., 'z':[...]}}, got {term!r}")
        c = float(term["c"])
        support = term["z"]
        if not isinstance(support, list) or not all(isinstance(x, int) for x in support):
            raise RunnerError(f"Invalid term[{t_idx}].z: expected list[int], got {support!r}")
        supp_sorted = tuple(sorted(int(x) for x in support))
        if len(set(supp_sorted)) != len(supp_sorted):
            raise RunnerError(f"Invalid term[{t_idx}].z has duplicates: {support!r}")
        for q in supp_sorted:
            if q < 0 or q >= n:
                raise RunnerError(f"Invalid term[{t_idx}].z index {q} out of range for n={n}")
        if len(supp_sorted) == 0:
            # global phase: drop
            continue
        accum[supp_sorted] = accum.get(supp_sorted, 0.0) + c

    # Keep deterministic ordering: by support length then lexicographic
    merged = sorted(accum.items(), key=lambda kv: (len(kv[0]), kv[0]))
    return [(supp, float(c)) for supp, c in merged if abs(c) > 0.0]


# Diagonal unitary synthesis (θ = -2c)
# -----------------------------------
# We implement the model convention:
#     U = Π_S exp(+i c_S Z_S)
# using Qiskit's primitive:
#     RZ(θ) = exp(-i θ/2 Z)
# so we must set θ = -2c. This is a *project-level invariant* enforced by policy.
#
# For |S|>=2 we use a simple "parity gadget" / CNOT ladder onto a pivot qubit:
#   - compute parity of Z_S onto pivot (CNOTs)
#   - apply RZ(θ) on pivot
#   - uncompute parity (reverse CNOTs)
# This pattern is backend-agnostic and matches YAML_to_Qiskit_Compiler_Guide.md.

def build_diagonal_u_circuit(n: int, terms: List[Tuple[Tuple[int, ...], float]], theta_rule: str = "-2c") -> "QuantumCircuit":
    """
    Build a QuantumCircuit implementing U = Π_S exp(i c_S Z_S) using θ=-2c.

    Synthesis patterns:
      |S|=1: RZ(-2c)
      |S|>=2: parity gadget with pivot = max(S) (CNOT ladder + RZ + uncompute)
    """
    ensure_qiskit_available()
    assert QuantumCircuit is not None

    if theta_rule != "-2c":
        raise PolicyError("Only theta_rule '-2c' is supported.")

    qc = QuantumCircuit(n, name="U_diag")

    for support, c in terms:
        theta = -2.0 * float(c)
        if len(support) == 1:
            (q,) = support
            qc.rz(theta, q)
        elif len(support) >= 2:
            # parity gadget to last qubit (pivot = max(support)), matches YAML_to_Qiskit_Compiler_Guide.
            pivot = support[-1]
            others = support[:-1]
            for q in others:
                qc.cx(q, pivot)
            qc.rz(theta, pivot)
            for q in reversed(others):
                qc.cx(q, pivot)

    return qc


# =============================================================================
# Protocol B circuit construction
# =============================================================================

# Protocol B note:
#   We build **exactly 4 circuits per (pair, context)** in a fixed order (SETTINGS):
#       cos_a, sin_a, cos_b, sin_b
#
#   In a multi‑pair run (protocol.pair is a list of pairs), a single "context block" contains:
#       (number_of_pairs × 4) circuits.
#
#   For drift-minimization we keep each (pair, context)'s 4 settings adjacent in the submitted list.
#   Each circuit measures ONLY qubit j into a 1-bit classical register named "meas".
#   This keeps counts parsing trivial and avoids multi-bit marginalization bugs.

@dataclass(frozen=True)
class CircuitTag:
    """A *side-channel* label for a circuit.

    Why we need this tag
    --------------------
    Qiskit `QuantumCircuit` objects have a `.metadata` field, and we *do* populate it
    for human debugging.

    However, relying on circuit metadata for correctness is fragile:
      - some transpiler passes may drop metadata
      - serialization / caching formats may not preserve it
      - backends typically do not return metadata in results

    Therefore we carry a parallel `tags` list aligned with the submitted circuit list.
    Every execution backend (statevector/fake_backend/qpu) zips `(circuits, tags)` so
    we can deterministically map each returned count histogram back to:
      (pair, context, setting).
    """

    # Which κ_{ij} this circuit contributes to.
    i: int
    j: int

    # Which spectator context (encoded as an integer over n-2 bits).
    z_rest_int: int

    # One of SETTINGS = (cos_a, sin_a, cos_b, sin_b).
    setting: str


# Protocol B circuit factory (4-setting U-only κ readout)
# -------------------------------------------------------
# For each context z_rest_int we generate 4 circuits in SETTINGS order.
#
# The circuit structure is (conceptually):
#   (1) prepare spectator/context bits (X gates) so the computational basis matches z_base
#   (2) choose |0> vs |1> on qubit i (a-setting vs b-setting) by optionally applying X(i)
#   (3) prepare |+> vs |+i> on qubit j (cos vs sin) using H and optional S
#   (4) apply the diagonal U
#   (5) rotate X-basis measurement back to Z with H(j), then measure j into a 1-bit register
#
# We measure *only* qubit j into a classical register named "meas" so the output is always
# a simple {"0":..,"1":..} histogram. This avoids downstream marginalization complexity.

def build_protocol_b_circuits(
    n: int,
    pairs: Sequence[Tuple[int, int]],
    contexts: Sequence[int],
    u_gate: Any,
) -> Tuple[List["QuantumCircuit"], List[CircuitTag]]:
    """
    Build Protocol B circuits for one *or more* diagnostic pairs.

    Output ordering is **context-major** (important for job packing):

        for each context z_rest_int:
            for each pair (i,j) in pairs:
                for each setting in SETTINGS:
                    append circuit

    Why this order?
      - For each (pair,context) the 4 settings are adjacent (drift-minimization within Protocol B).
      - All pairs share the same context "time slice" when auto-splitting by context blocks.

    Each circuit measures ONLY qubit j into meas[0] (1-bit register named "meas").
    """
    ensure_qiskit_available()
    assert QuantumCircuit is not None and ClassicalRegister is not None

    if not pairs:
        raise ValueError("pairs must be a non-empty sequence")

    circuits: List[QuantumCircuit] = []
    tags: List[CircuitTag] = []

    for z_rest_int in contexts:
        z_rest_int = int(z_rest_int)

        for (i_raw, j_raw) in pairs:
            # Canonicalize each pair; we treat κ_{ij} as an unordered pair invariant.
            i, j = sorted_pair(int(i_raw), int(j_raw))
            z_base = unpack_z_rest(z_rest_int, n, i, j)

            for setting in SETTINGS:
                # Include pair in the name so multi-pair runs have unique circuit names.
                qc = QuantumCircuit(n, name=f"p{i}_{j}_ctx{z_rest_int}_{setting}")
                meas = ClassicalRegister(1, "meas")
                qc.add_register(meas)

                # 1) context bits on q != i,j
                for q in range(n):
                    if q in (i, j):
                        continue
                    if (z_base >> q) & 1:
                        qc.x(q)

                # 2) prepare i (a vs b)
                if setting.endswith("_b"):
                    qc.x(i)

                # 3) prepare j (cos vs sin)
                qc.h(j)
                if setting.startswith("sin_"):
                    qc.s(j)

                # 4) apply U
                qc.append(u_gate, list(range(n)))

                # 5) measure j in X basis via H, then Z-measure
                qc.h(j)
                qc.measure(j, meas[0])

                # metadata (best effort; do not rely on it for correctness)
                qc.metadata = {"z_rest_int": z_rest_int, "setting": setting, "pair": [i, j]}

                circuits.append(qc)
                tags.append(CircuitTag(i=int(i), j=int(j), z_rest_int=z_rest_int, setting=setting))

    return circuits, tags


# =============================================================================
# Statevector expectation helper
# =============================================================================

# Statevector note:
#   In statevector mode we compute exact expectations (<Z_j>) deterministically.
#   This gives an unambiguous reference for m1..m4 and is also used for the preflight phasor check.
#   (We still write counts.json, but in this mode it stores probabilities instead of integer counts.)

def expectation_z_from_statevector(state: "Statevector", qubit: int) -> float:
    """
    Compute <Z_qubit> from a Statevector using the Qiskit amplitude ordering convention
    (q0 is LSB). We avoid relying on qargs ordering helpers.
    """
    data = state.data  # numpy array of amplitudes
    p1 = 0.0
    for idx, amp in enumerate(data):
        if (idx >> qubit) & 1:
            p1 += float((amp.real * amp.real) + (amp.imag * amp.imag))
    # <Z> = P0 - P1 = 1 - 2 P1
    return 1.0 - 2.0 * p1


def statevector_expectation_for_setting(
    n: int,
    i: int,
    j: int,
    z_rest_int: int,
    setting: str,
    u_gate: Any,
) -> float:
    """
    Build the unitary part of the Protocol B circuit (no measurement), then compute <Z_j>.
    This equals the desired m_k (cos/sin) in the ideal model.
    """
    ensure_qiskit_available()
    assert QuantumCircuit is not None and Statevector is not None

    i, j = sorted_pair(i, j)

    z_base = unpack_z_rest(int(z_rest_int), n, i, j)

    qc = QuantumCircuit(n, name=f"sv_ctx{int(z_rest_int)}_{setting}")

    # context
    for q in range(n):
        if q in (i, j):
            continue
        if (z_base >> q) & 1:
            qc.x(q)

    # i
    if setting.endswith("_b"):
        qc.x(i)

    # j
    qc.h(j)
    if setting.startswith("sin_"):
        qc.s(j)

    qc.append(u_gate, list(range(n)))

    qc.h(j)

    sv = Statevector.from_instruction(qc)
    return float(expectation_z_from_statevector(sv, j))


# =============================================================================
# Fake backend (Aer) noise model
# =============================================================================

# Fake-backend note:
#   This is a *rehearsal* environment, not a high-fidelity noise model.
#   Minimum requirement is readout error (p10/p01) extracted from the snapshot.
#   Optional gate noise uses a crude depolarizing approximation from snapshot.gate_properties.

# Aer noise model builder (snapshot-derived rehearsal)
# ----------------------------------------------------
# This intentionally implements a *minimal* noise model for fake_backend mode:
#   - ReadoutError per qubit from snapshot.prob_meas1_prep0 / prob_meas0_prep1
#   - Optional depolarizing gate noise (very crude) from snapshot.gate_properties[*].error
# The goal is not perfect physical realism, but a reproducible "noisy rehearsal" that helps
# catch gross robustness issues before consuming QPU time.

def build_noise_model_from_snapshot(
    snapshot: BackendSnapshot,
    enable_gate_noise: bool = False,
    *,
    physical_qubits: Optional[Sequence[int]] = None,
) -> "NoiseModel":
    """Build an Aer NoiseModel from a frozen backend snapshot.

    Why this function is subtle (and easy to get wrong)
    -----------------------------------------------
    The backend snapshot JSON is indexed by **physical qubit id** (0..num_qubits-1)
    for a particular IBM device.

    But the circuits we execute in this runner are typically **n‑qubit circuits** with
    virtual indices 0..n-1. In fake_backend/qpu modes we *pin* those virtual qubits to
    specific physical qubits via `initial_layout = hardware_meta.physical_qubits`.

    Qiskit Aer applies noise by **circuit qubit index**, not by the device's physical id.

    Therefore the correct rule for snapshot‑derived noise in this project is:

      - **Fetch parameters from physical qubits**, using the model's logical→physical mapping.
      - **Attach the noise to the circuit's virtual qubits** (0..n-1).

    This is exactly the fix requested in the code review feedback:
      "value is from physical, application is to virtual index".

    What we model (minimal rehearsal)
    --------------------------------
    - ReadoutError per qubit from snapshot.prob_meas1_prep0 / prob_meas0_prep1.
      This is the minimum meaningful rehearsal noise for κ‑litmus Protocol B.

    - Optional gate noise (enable_gate_noise=True): a crude depolarizing channel whose
      strength is snapshot.gate_properties[gate][qubits].error.

      IMPORTANT: this is *not* intended as a high-fidelity physical model. It is a
      reproducible stress test that can catch gross robustness issues before using QPU time.

    Parameters
    ----------
    snapshot:
        Parsed BackendSnapshot.
    enable_gate_noise:
        If True, include a crude depolarizing approximation for gate errors.
    physical_qubits:
        Optional list[int] of length n mapping logical/virtual index -> physical qubit id.
        If provided, readout (and optional gate) errors are taken from those physical qubits
        but attached to virtual indices 0..n-1.

        If None, we fall back to the identity mapping (virtual==physical). This is mostly
        useful for debugging; in κ‑litmus fake_backend mode we normally REQUIRE a mapping.
    """

    ensure_aer_available()
    assert NoiseModel is not None and ReadoutError is not None

    noise = NoiseModel()

    # -----------------------------
    # 3.1 Readout errors (critical)
    # -----------------------------
    # We only attach readout errors for the qubits that exist in the circuit.
    # If physical_qubits is provided, its length defines the circuit size n.
    if physical_qubits is None:
        # Identity mapping: virtual q -> physical q.
        # Note: we cannot infer the circuit size from the snapshot; in this fallback we
        # attach errors for all physical qubits and rely on Aer to ignore those not present.
        virt_to_phys = list(range(snapshot.num_qubits))
    else:
        virt_to_phys = [int(x) for x in physical_qubits]

    for virt_q, phys_q in enumerate(virt_to_phys):
        # Snapshot values are keyed by physical id.
        ro = snapshot.readout_error_for_qubit(int(phys_q))
        if ro is None:
            continue
        p10, p01 = ro
        # ReadoutError matrix rows: measured 0/1; cols: prepared 0/1
        mat = [[1.0 - p10, p01], [p10, 1.0 - p01]]
        try:
            # Apply to the *virtual* wire index.
            noise.add_readout_error(ReadoutError(mat), [int(virt_q)])
        except Exception:
            # Malformed entries should not kill the whole run.
            continue

    # ------------------------------------------
    # 3.2 Optional gate noise (best-effort only)
    # ------------------------------------------
    if enable_gate_noise:
        assert depolarizing_error is not None

        # Build an inverse mapping physical -> virtual so we can translate snapshot keys.
        # If we cannot map a gate's qubit tuple into our circuit's subset, we skip it.
        phys_to_virt: Optional[Dict[int, int]] = None
        if physical_qubits is not None:
            phys_to_virt = {int(p): int(v) for v, p in enumerate(virt_to_phys)}

        # gate_properties format in our snapshot JSON is:
        #   gate_properties[gate_name]["[0, 1]"] = {"error": <float>, "duration": <float>, ...}
        # Note the qubit key string may look like "[0, 1]" or "0,1" depending on producer.
        for gate, table in snapshot.gate_properties.items():
            if not isinstance(table, dict):
                continue

            for qubits_str, props in table.items():
                if not isinstance(props, dict):
                    continue

                p = props.get("error")
                if not isinstance(p, (int, float)):
                    continue
                p = float(p)
                if p <= 0.0 or p >= 1.0:
                    continue

                # Robust qubit tuple parsing (fixes "[0, 1]" vs "0,1" issue).
                # We intentionally ignore punctuation and just extract integer tokens.
                qs_tokens = re.findall(r"\d+", str(qubits_str))
                if not qs_tokens:
                    continue
                qs_phys = tuple(int(x) for x in qs_tokens)

                # Translate physical tuple -> virtual tuple if mapping is available.
                if phys_to_virt is not None:
                    try:
                        qs_virt = tuple(phys_to_virt[int(pq)] for pq in qs_phys)
                    except Exception:
                        # Gate touches a qubit outside our mapped subgraph.
                        continue
                else:
                    qs_virt = qs_phys

                if len(qs_virt) == 0:
                    continue

                # Depolarizing channel on k qubits.
                try:
                    err = depolarizing_error(p, len(qs_virt))
                    noise.add_quantum_error(err, str(gate), list(qs_virt))
                except Exception:
                    continue

    return noise


# =============================================================================
# Counts parsing
# =============================================================================

# Counts normalization note:
#   Even though Protocol B is designed to yield a 1-bit count dict {"0":..,"1":..},
#   different backends/versions may return counts in slightly different encodings.
#   We normalize everything to {"0": int, "1": int} to keep downstream reconstruction uniform.

# Counts normalizer (make all backends look the same)
# ---------------------------------------------------
# Protocol B is designed to measure a single classical bit, but depending on the backend/API
# we may get counts in different representations (dict, quasi-dist, hex keys, multi-bit strings).
# This helper aggressively coerces anything "counts-like" to {"0": int, "1": int}.
# If the outcome is a bitstring, we take the *last* character because Qiskit prints classical
# bitstrings with c0 as the rightmost bit.

def coerce_counts_01(raw_counts: Any, *, shots_hint: Optional[int] = None) -> Dict[str, int]:
    """Normalize arbitrary Qiskit counts-like output to {"0": int, "1": int}.

    Why we need this helper
    -----------------------
    In an ideal world every backend would return a plain dict like {"0": 512, "1": 512}.
    In practice, depending on backend + Qiskit/Runtime versions, you may see:
      - plain integer counts
      - dicts keyed by ints (0/1)
      - hex strings ("0x0", "0x1")
      - quasi distributions / probabilities (floats that sum to 1)

    κ‑litmus Protocol B measures a **single classical bit** (meas[0]). This function
    collapses any representation into a single-bit count dictionary.

    shots_hint
    ----------
    If provided and the values look like probabilities (sum ≈ 1), we convert probabilities
    into pseudo-counts by rounding p*shots_hint. This is primarily to make SamplerV2
    results robust when it returns a QuasiDist-like object instead of raw counts.
    """

    if raw_counts is None:
        return {"0": 0, "1": 0}

    # Convert to an iterable of (outcome, value) pairs.
    if isinstance(raw_counts, dict):
        items = list(raw_counts.items())
    else:
        try:
            items = list(dict(raw_counts).items())
        except Exception:
            return {"0": 0, "1": 0}

    parsed: List[Tuple[int, float]] = []  # (bit, numeric_value)

    # ---------------------------
    # Parse outcomes + raw values
    # ---------------------------
    for outcome, value in items:
        # 1) outcome -> bit {0,1}
        bit: Optional[int] = None
        if isinstance(outcome, int):
            bit = int(outcome) & 1
        else:
            s = str(outcome).replace(" ", "")
            if s.startswith("0x"):
                try:
                    bit = int(s, 16) & 1
                except Exception:
                    bit = None
            else:
                # Qiskit prints classical bitstrings with c0 as the rightmost bit.
                if len(s) >= 1 and s[-1] in ("0", "1"):
                    bit = int(s[-1])

        if bit not in (0, 1):
            continue

        # 2) value -> float (keep as float for now; we'll decide counts vs probs later)
        if isinstance(value, bool):
            # Avoid treating True/False as 1/0 counts.
            continue

        try:
            v = float(value)
        except Exception:
            continue

        if v < 0:
            # Defensive: negative weights are not meaningful here.
            continue

        parsed.append((int(bit), float(v)))

    if not parsed:
        return {"0": 0, "1": 0}

    # -------------------------------------------------
    # Heuristic: decide if parsed values are counts/prob
    # -------------------------------------------------
    total = sum(v for _, v in parsed)

    # If values look like probabilities (sum ~ 1) and shots_hint is available, scale.
    if shots_hint is not None and total > 0.0 and total <= 1.0 + 1e-6:
        p0 = sum(v for b, v in parsed if b == 0)
        p1 = sum(v for b, v in parsed if b == 1)
        norm = p0 + p1
        if norm > 0:
            p0 /= norm
            p1 /= norm

        c0 = int(round(p0 * int(shots_hint)))
        c1 = int(round(p1 * int(shots_hint)))

        # Fix rounding drift so c0+c1 == shots_hint.
        diff = int(shots_hint) - (c0 + c1)
        if diff != 0:
            if p1 >= p0:
                c1 += diff
            else:
                c0 += diff

        return {"0": max(0, int(c0)), "1": max(0, int(c1))}

    # Otherwise treat as counts-like and round.
    c0 = int(round(sum(v for b, v in parsed if b == 0)))
    c1 = int(round(sum(v for b, v in parsed if b == 1)))
    return {"0": max(0, int(c0)), "1": max(0, int(c1))}


def expectation_from_counts_01(counts_01: Dict[str, int]) -> Tuple[float, int]:
    shots = int(counts_01.get("0", 0) + counts_01.get("1", 0))
    if shots <= 0:
        return (0.0, 0)
    m = (counts_01.get("0", 0) - counts_01.get("1", 0)) / float(shots)
    return (float(m), shots)


# =============================================================================
# Analytics (a_true, b_true, kappa_true)
# =============================================================================

# Targets note:
#   In fake_backend/qpu modes, *_true values are *model targets* computed from φ(z) in the YAML model.
#   They are NOT "hardware truth". We store them to enable intended-vs-measured comparisons and
#   κ-profile visualization without needing to re-load the model later.

@dataclass(frozen=True)
class Targets:
    a_true: float
    b_true: float
    kappa_true: float


def compute_targets(provider: ModelProvider, n: int, i: int, j: int, contexts: Sequence[int]) -> Dict[int, Targets]:
    out: Dict[int, Targets] = {}
    i, j = sorted_pair(i, j)
    for z_rest_int in contexts:
        z00, z10, z01, z11 = face_vertices(int(z_rest_int), n, i, j)
        phi00 = provider.get_diag_value(z00)
        phi10 = provider.get_diag_value(z10)
        phi01 = provider.get_diag_value(z01)
        phi11 = provider.get_diag_value(z11)
        a = float(phi00 - phi01)
        b = float(phi10 - phi11)
        kappa = wrap_to_pi(a - b)
        out[int(z_rest_int)] = Targets(a_true=a, b_true=b, kappa_true=kappa)
    return out


# =============================================================================
# Preflight validation (statevector phasor check)
# =============================================================================

# Validation note:
#   The most common catastrophic bugs are convention mismatches:
#     - wrong θ sign (theta_rule)
#     - wrong bit order / context insertion
#     - swapped i/j or inconsistent face vertex ordering
#   The phasor check compares analytic exp(i·a), exp(i·b), exp(i·κ) against exact statevector results
#   on a handful of contexts, failing fast with actionable hints.

@dataclass(frozen=True)
class ValidationReport:
    contexts_checked: List[int]
    max_err_u_a: float
    max_err_u_b: float
    max_err_u_kappa: float
    passed: bool
    tol: float


def preflight_validate_phasors(
    n: int,
    i: int,
    j: int,
    contexts: Sequence[int],
    provider: ModelProvider,
    u_gate: Any,
    tol: float = 1e-9,
    max_contexts: int = 4,
) -> ValidationReport:
    """
    Compare analytic phasors vs exact statevector values:
      u_a = cos(a) + i sin(a)
      u_b = cos(b) + i sin(b)
      u_kappa = u_a * conj(u_b)
    """
    ensure_qiskit_available()

    checked = list(contexts[: min(len(contexts), max_contexts)])

    max_err_a = 0.0
    max_err_b = 0.0
    max_err_k = 0.0

    for z_rest_int in checked:
        z_rest_int = int(z_rest_int)
        z00, z10, z01, z11 = face_vertices(z_rest_int, n, i, j)
        phi00 = provider.get_diag_value(z00)
        phi10 = provider.get_diag_value(z10)
        phi01 = provider.get_diag_value(z01)
        phi11 = provider.get_diag_value(z11)

        a_true = float(phi00 - phi01)
        b_true = float(phi10 - phi11)
        u_a_true = cmath.exp(1j * a_true)
        u_b_true = cmath.exp(1j * b_true)
        u_k_true = u_a_true * u_b_true.conjugate()

        # statevector "measurements"
        m1 = statevector_expectation_for_setting(n, i, j, z_rest_int, "cos_a", u_gate)
        m2 = statevector_expectation_for_setting(n, i, j, z_rest_int, "sin_a", u_gate)
        m3 = statevector_expectation_for_setting(n, i, j, z_rest_int, "cos_b", u_gate)
        m4 = statevector_expectation_for_setting(n, i, j, z_rest_int, "sin_b", u_gate)

        u_a_hat = complex(m1, m2)
        u_b_hat = complex(m3, m4)
        u_k_hat = u_a_hat * u_b_hat.conjugate()

        err_a = abs(u_a_hat - u_a_true)
        err_b = abs(u_b_hat - u_b_true)
        err_k = abs(u_k_hat - u_k_true)

        max_err_a = max(max_err_a, float(err_a))
        max_err_b = max(max_err_b, float(err_b))
        max_err_k = max(max_err_k, float(err_k))

    passed = (max_err_a <= tol) and (max_err_b <= tol) and (max_err_k <= tol)
    return ValidationReport(
        contexts_checked=checked,
        max_err_u_a=max_err_a,
        max_err_u_b=max_err_b,
        max_err_u_kappa=max_err_k,
        passed=passed,
        tol=tol,
    )


# =============================================================================
# Transpile + caching (QPY)
# =============================================================================

# Freeze/reuse note:
#   Transpilation is stochastic and version-sensitive. For meaningful comparisons across runs
#   (and especially across fake_backend ↔ qpu), we optionally freeze transpiled circuits as QPY.
#   A cache_key encodes model+snapshot+compile+protocol+versions, so reuse is safe and explicit.

@dataclass
class FrozenCircuitsInfo:
    cache_key: str
    cache_dir: Path
    cache_qpy_path: Path
    cache_manifest_path: Path
    run_qpy_path: Optional[Path]
    run_manifest_path: Optional[Path]
    reused: bool


def compute_cache_key(
    model_yaml_hash: str,
    snapshot_hash: str,
    compile_block: Dict[str, Any],
    protocol_signature: Dict[str, Any],
    versions: Dict[str, str],
) -> str:
    payload = {
        "model_yaml_hash": model_yaml_hash,
        "snapshot_hash": snapshot_hash,
        "compile": compile_block,
        "protocol": protocol_signature,
        "versions": versions,
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def protocol_signature_for_cache(
    protocol_block: Dict[str, Any],
    contexts: Sequence[int],
    max_list_store: int = 4096,
) -> Dict[str, Any]:
    """
    Cache signature for protocol: include name/pair/context mode parameters + a hash of the concrete context list.
    Store full list only if it's small.
    """
    ctx_list = [int(x) for x in contexts]
    ctx_hash = sha256_bytes(json.dumps(ctx_list, separators=(",", ":"), sort_keys=False).encode("utf-8"))
    ctx_block = dict(protocol_block.get("context", {}))
    sig: Dict[str, Any] = {
        "name": protocol_block.get("name"),
        "pair": protocol_block.get("pair"),
        "context": ctx_block,
        "contexts_sha256": ctx_hash,
    }
    if len(ctx_list) <= max_list_store:
        sig["contexts"] = ctx_list
    else:
        sig["contexts_preview"] = ctx_list[: min(16, len(ctx_list))]
        sig["contexts_count"] = len(ctx_list)
    return sig


def maybe_load_frozen_circuits(
    cache_key: str,
    cache_dir: Path,
) -> Optional[List["QuantumCircuit"]]:
    """Load frozen circuits from cache if present."""
    ensure_qiskit_available()
    assert qpy is not None

    qpy_path = cache_dir / f"{cache_key}.qpy"
    manifest_path = cache_dir / f"{cache_key}.json"
    if not qpy_path.exists() or not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("cache_key") != cache_key:
            return None
    except Exception:
        return None

    with open(qpy_path, "rb") as f:
        circuits = qpy.load(f)
    # qpy.load can return a list or iterator
    return list(circuits)


def save_frozen_circuits(
    circuits: List["QuantumCircuit"],
    cache_key: str,
    cache_dir: Path,
    run_circuits_dir: Optional[Path],
    meta: Dict[str, Any],
) -> FrozenCircuitsInfo:
    """Save QPY circuits to cache and run artifacts directory."""
    ensure_qiskit_available()
    assert qpy is not None

    cache_dir.mkdir(parents=True, exist_ok=True)
    qpy_path = cache_dir / f"{cache_key}.qpy"
    manifest_path = cache_dir / f"{cache_key}.json"

    # Write cache QPY
    with open(qpy_path, "wb") as f:
        qpy.dump(circuits, f)

    manifest = {
        "cache_key": cache_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "num_circuits": len(circuits),
        "meta_preview": meta,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    run_qpy_path = None
    run_manifest_path = None
    if run_circuits_dir is not None:
        run_circuits_dir.mkdir(parents=True, exist_ok=True)
        run_qpy_path = run_circuits_dir / "transpiled.qpy"
        run_manifest_path = run_circuits_dir / "manifest.json"
        # Copy into run dir as well (portable)
        with open(run_qpy_path, "wb") as f:
            qpy.dump(circuits, f)
        run_manifest = dict(manifest)
        run_manifest["cache_qpy_path"] = str(qpy_path)
        run_manifest["cache_manifest_path"] = str(manifest_path)
        run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    return FrozenCircuitsInfo(
        cache_key=cache_key,
        cache_dir=cache_dir,
        cache_qpy_path=qpy_path,
        cache_manifest_path=manifest_path,
        run_qpy_path=run_qpy_path,
        run_manifest_path=run_manifest_path,
        reused=False,
    )


# =============================================================================
# Execution backends
# =============================================================================

# Execution note:
#   Regardless of mode, the pipeline is:
#     circuits -> (counts/probabilities) -> <Z> expectations -> phasors -> κ̂ + amp metrics
#   Each execution function returns per-circuit entries aligned with CircuitTag metadata so we can
#   reconstruct per-context rows without relying on backend execution ordering.

def execute_statevector(
    n: int,
    i: int,
    j: int,
    contexts: Sequence[int],
    targets: Dict[int, Targets],
    u_gate: Any,
    bit_order: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Ideal execution: compute exact expectations (m1..m4) via statevector.
    Returns: (rows, counts_json_payload)
    """
    ensure_qiskit_available()

    rows: List[Dict[str, Any]] = []
    counts_data: List[Dict[str, Any]] = []

    for z_rest_int in contexts:
        z_rest_int = int(z_rest_int)
        m: Dict[str, float] = {}
        probs: Dict[str, Tuple[float, float]] = {}

        # compute expectations per setting
        for setting in SETTINGS:
            # Build unitary-only circuit and get statevector expectation
            m_val = statevector_expectation_for_setting(n, i, j, z_rest_int, setting, u_gate)
            m[setting] = float(m_val)

            # Also compute probabilities (p0,p1) for counts.json (optional utility)
            # We do it by reconstructing p1 from <Z>: <Z>=p0-p1=1-2p1
            p1 = 0.5 * (1.0 - m_val)
            p0 = 1.0 - p1
            probs[setting] = (float(p0), float(p1))

        u_a = complex(m["cos_a"], m["sin_a"])
        u_b = complex(m["cos_b"], m["sin_b"])
        kappa_hat = angle_of(u_a * u_b.conjugate())

        t = targets[z_rest_int]

        row = {
            "n": int(n),
            "i": int(i),
            "j": int(j),
            "z_rest_int": int(z_rest_int),
            "trial_id": 0,
            "kappa_true": float(t.kappa_true),
            "kappa_hat": float(kappa_hat),
            "a_true": float(t.a_true),
            "b_true": float(t.b_true),
            "cos_a_hat": float(m["cos_a"]),
            "sin_a_hat": float(m["sin_a"]),
            "cos_b_hat": float(m["cos_b"]),
            "sin_b_hat": float(m["sin_b"]),
            "amp_a": float(abs(u_a)),
            "amp_b": float(abs(u_b)),
        }
        rows.append(row)

        # counts.json entries (probabilities, not integer counts)
        for setting in SETTINGS:
            p0, p1 = probs[setting]
            counts_data.append(
                {
                    "z_rest_int": int(z_rest_int),
                    "setting": setting,
                    "shots": 0,
                    "counts": {"0": p0, "1": p1},
                }
            )

    counts_payload = {
        "schema": "counts.v1",
        "n": int(n),
        "pair": [int(i), int(j)],
        "bit_order": str(bit_order),
        "settings": list(SETTINGS),
        "shots_per_circuit": 0,
        "data": counts_data,
        "note": "statevector mode: counts are probabilities (floats), shots=0",
    }

    return rows, counts_payload


def execute_fake_backend(
    circuits: List["QuantumCircuit"],
    tags: List[CircuitTag],
    snapshot: BackendSnapshot,
    shots: int,
    enable_gate_noise: bool,
    *,
    physical_qubits: Optional[Sequence[int]],
) -> List[Dict[str, Any]]:
    """Execute circuits on an AerSimulator configured as a "fake backend".

    Why fake_backend exists in κ‑litmus
    ----------------------------------
    Hardware time is expensive and queueing is unpredictable. We therefore want a
    deterministic rehearsal mode that is *closer to hardware constraints* than a pure
    statevector simulation.

    The goal is NOT a perfect noise model; the goal is to:
      - reuse the same transpiled circuits we would send to QPU (layout/routing fixed)
      - add at least readout error in a way that respects our physical mapping
      - catch gross bugs / instability before a real run

    Mapping subtlety (high risk)
    ----------------------------
    - `snapshot` properties (readout/gate errors) are indexed by physical qubit id.
    - Aer noise attaches to circuit qubit indices.

    We therefore pass `physical_qubits` (logical→physical) into the noise builder so that
    readout error values are taken from the intended physical wires but applied to the
    circuit's virtual indices.
    """

    ensure_aer_available()
    assert AerSimulator is not None and CouplingMap is not None

    noise = build_noise_model_from_snapshot(
        snapshot,
        enable_gate_noise=enable_gate_noise,
        physical_qubits=physical_qubits,
    )

    # NOTE: We pass the full-device coupling map / basis gates to AerSimulator to mimic the
    # target backend constraints. Circuits were already transpiled against the same snapshot.
    coupling = CouplingMap(snapshot.coupling_map)
    backend = AerSimulator(
        noise_model=noise,
        coupling_map=coupling,
        basis_gates=filter_basis_gates(snapshot.basis_gates),
    )

    job = backend.run(circuits, shots=int(shots))
    result = job.result()

    out: List[Dict[str, Any]] = []
    for circ, tag in zip(circuits, tags):
        raw = result.get_counts(circ)
        counts01 = coerce_counts_01(raw, shots_hint=int(shots))
        out.append(
            {
                # NOTE: pair is recorded per-circuit so a single Runtime job can
                # contain multiple κ_{ij} readouts (reviewer-friendly control runs).
                "pair": [int(tag.i), int(tag.j)],
                "z_rest_int": int(tag.z_rest_int),
                "setting": tag.setting,
                "shots": int(counts01["0"] + counts01["1"]),
                "counts": counts01,
            }
        )

    return out


def _sampler_pub_get_counts(pub_result: Any, *, shots_hint: Optional[int] = None) -> Dict[str, int]:
    """Best-effort extraction for SamplerV2 per-circuit results.

    Runtime APIs evolve, and SamplerV2 can surface measurement results in multiple forms.
    The runner's downstream reconstruction only needs a 1-bit {"0":..,"1":..} object.

    We therefore:
      1) Locate the measurement field (we name the classical register "meas" in circuits).
      2) Prefer .get_counts() if available.
      3) Fall back to dict-like conversion.
      4) Normalize using coerce_counts_01, optionally converting quasi/prob outputs using shots_hint.

    If you see this fail, it usually means the Sampler result schema changed in your
    installed qiskit-ibm-runtime version.
    """

    data = getattr(pub_result, "data", None)
    if data is None:
        raise ExecutionError("SamplerV2 result item has no .data attribute")

    meas_obj = None

    # 1) Preferred: attribute access by name
    if hasattr(data, "meas"):
        meas_obj = getattr(data, "meas")

    # 2) Alternate: dict-like access
    elif isinstance(data, dict) and "meas" in data:
        meas_obj = data["meas"]

    else:
        # 3) Heuristic: if data has a single field, treat it as measurement.
        try:
            vals = list(data.values())  # type: ignore[attr-defined]
            if len(vals) == 1:
                meas_obj = vals[0]
        except Exception:
            pass

    if meas_obj is None:
        raise ExecutionError("SamplerV2 data has no 'meas' field; ensure creg is named 'meas'")

    # If the measurement object provides a counts API, use it.
    if hasattr(meas_obj, "get_counts"):
        raw = meas_obj.get_counts()
        return coerce_counts_01(raw, shots_hint=shots_hint)

    # If it's already a mapping, normalize directly.
    if isinstance(meas_obj, dict):
        return coerce_counts_01(meas_obj, shots_hint=shots_hint)

    # Last resort: cast to dict.
    try:
        return coerce_counts_01(dict(meas_obj), shots_hint=shots_hint)
    except Exception as e:
        raise ExecutionError(f"Could not extract counts from SamplerV2 meas object: {type(meas_obj)}") from e


# QPU execution (IBM Runtime SamplerV2, job mode)
# ----------------------------------------------
# Hardware runs are the most failure-prone part of the pipeline (network, queueing, limits).
# We therefore:
#   - optionally split the circuit list into batches that respect backend limits
#   - NEVER split within a context *block*
#       * single-pair run : 4 circuits per context
#       * multi-pair run  : (num_pairs × 4) circuits per context
#     (otherwise κ̂ reconstruction would mix job ids / drift conditions)
#   - implement per-job and global timeouts (best-effort, version-compatible)
#   - retry failed batches with exponential backoff (max_retries)
# The returned jobs_meta is written into run_meta.json for post-mortem debugging.

def execute_qpu_batches(
    circuits: List["QuantumCircuit"],
    tags: List[CircuitTag],
    # IMPORTANT: atomic block size for job splitting.
    #
    # A "context block" is the smallest set of circuits we must keep together
    # to reconstruct κ̂ without cross-job mixing:
    #   - single-pair run: 4 circuits (cos_a, sin_a, cos_b, sin_b)
    #   - multi-pair run with P pairs: P * 4 circuits per context
    #
    # We pass this explicitly instead of inferring it from the circuit list to
    # keep the batching logic simple and reviewable.
    circuits_per_context_block: int,
    cfg: Dict[str, Any],
    snapshot: BackendSnapshot,
    selected_backend_name: str,
    shots: int,
    job_timeout_s: Optional[float],
    global_timeout_s: Optional[float],
    max_retries: int = 3,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Execute circuits on IBM QPU with SamplerV2, possibly split into batches.
    Returns (counts_entries, jobs_meta).
    """
    ensure_ibm_runtime_available()
    assert QiskitRuntimeService is not None and SamplerV2 is not None

    start_wall = time.time()

    ibm_cfg = cfg["ibm"]
    service = create_ibm_service(ibm_cfg)

    backend_name = selected_backend_name
    backend = service.backend(backend_name)

    sampler = SamplerV2(mode=backend)

    # Determine batch sizing
    auto_split = bool(cfg["job"]["auto_split"])
    max_circuits_per_job = int(cfg["job"]["max_circuits_per_job"])
    max_exec_per_job = int(cfg["job"]["max_executions_per_job"])

    # Also respect snapshot limits if present (should match backend)
    snap_max_experiments = snapshot.max_experiments()
    if snap_max_experiments is not None:
        max_circuits_per_job = min(max_circuits_per_job, int(snap_max_experiments))
    snap_max_shots = snapshot.max_shots()
    if snap_max_shots is not None and shots > int(snap_max_shots):
        raise PolicyError(f"shots={shots} exceeds backend snapshot max_shots={snap_max_shots}")

    if not auto_split:
        batches = [(0, len(circuits))]
    else:
        # Ensure we don't split within a **context block**.
        #
        # In multi-pair runs this is crucial: if you split a (pair,context)
        # 4-setting bundle across jobs you reintroduce the exact reviewer concern
        # we are trying to avoid (different job ids for related measurements).
        per_block = int(circuits_per_context_block)
        if per_block <= 0:
            raise ExecutionError(f"circuits_per_context_block must be positive, got {per_block}")
        if len(circuits) % per_block != 0:
            raise ExecutionError(
                "Internal error: circuit list length is not a multiple of the context block size. "
                f"len(circuits)={len(circuits)}, per_block={per_block}. "
                "This usually indicates the build_protocol_b_circuits ordering contract was violated."
            )

        max_blocks_by_circuits = max(1, max_circuits_per_job // per_block)
        max_blocks_by_exec = max(1, max_exec_per_job // (shots * per_block))
        blocks_per_batch = max(1, min(max_blocks_by_circuits, max_blocks_by_exec))
        batch_size = blocks_per_batch * per_block

        batches = []
        s = 0
        while s < len(circuits):
            e = min(len(circuits), s + batch_size)
            # keep block boundary
            e = s + ((e - s) // per_block) * per_block
            if e == s:
                e = min(len(circuits), s + per_block)
            batches.append((s, e))
            s = e

    all_counts: List[Dict[str, Any]] = []
    jobs_meta: List[Dict[str, Any]] = []

    for b_idx, (s, e) in enumerate(batches):
        if global_timeout_s is not None and (time.time() - start_wall) > global_timeout_s:
            raise ExecutionError(f"Global timeout exceeded ({global_timeout_s}s) before batch {b_idx}")

        batch_circs = circuits[s:e]
        batch_tags = tags[s:e]

        attempt = 0
        while True:
            try:
                job = sampler.run(batch_circs, shots=shots)
                job_id = getattr(job, "job_id", lambda: None)()
                jobs_meta.append(
                    {
                        "batch_index": b_idx,
                        "start": s,
                        "end": e,
                        "num_circuits": len(batch_circs),
                        "shots": shots,
                        "job_id": job_id,
                        "status_submitted_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

                # Wait for result (best effort)
                if job_timeout_s is None:
                    result = job.result()
                else:
                    try:
                        result = job.result(timeout=job_timeout_s)
                    except TypeError:
                        # Some versions use positional timeout
                        result = job.result(job_timeout_s)

                # result is iterable, aligned to pubs
                for pub_result, tag in zip(result, batch_tags):
                    counts01 = _sampler_pub_get_counts(pub_result, shots_hint=shots)
                    all_counts.append(
                        {
                            "pair": [int(tag.i), int(tag.j)],
                            "z_rest_int": int(tag.z_rest_int),
                            "setting": tag.setting,
                            "shots": int(counts01["0"] + counts01["1"]),
                            "counts": counts01,
                        }
                    )
                break  # success

            except Exception as ex:
                attempt += 1
                jobs_meta.append(
                    {
                        "batch_index": b_idx,
                        "start": s,
                        "end": e,
                        "attempt": attempt,
                        "error": repr(ex),
                        "time": datetime.now(timezone.utc).isoformat(),
                    }
                )
                if attempt >= max_retries:
                    raise ExecutionError(f"Batch {b_idx} failed after {max_retries} attempts: {ex}") from ex
                # Exponential backoff
                time.sleep(2 ** attempt)

    return all_counts, jobs_meta


def select_backend_name(cfg: Dict[str, Any], n: int) -> str:
    """Select backend name (auto vs explicit) for qpu mode."""
    ensure_ibm_runtime_available()
    assert QiskitRuntimeService is not None

    service = create_ibm_service(cfg["ibm"])
    backend_cfg = cfg["backend"]
    name = backend_cfg["name"]

    if name != "auto":
        return str(name)

    # Auto selection
    min_nq = backend_cfg["min_num_qubits"]
    if min_nq == "from_model":
        min_qubits = int(n)
    else:
        min_qubits = int(min_nq)

    candidates = service.backends()
    filtered = []
    for b in candidates:
        try:
            if int(getattr(b, "num_qubits", 0)) < min_qubits:
                continue
            if bool(backend_cfg.get("require_operational", True)) and not bool(getattr(b, "operational", True)):
                continue
            filtered.append(b)
        except Exception:
            continue

    if not filtered:
        raise ExecutionError(f"No operational backend found with >= {min_qubits} qubits.")

    # Use least_busy if available, otherwise pick by pending_jobs
    if _least_busy_available and least_busy is not None:
        chosen = least_busy(filtered)
    else:
        # Manual least_busy: pick backend with fewest pending jobs
        def get_pending(b):
            try:
                status = b.status()
                return getattr(status, "pending_jobs", 999999)
            except Exception:
                return 999999
        chosen = min(filtered, key=get_pending)
    
    return str(getattr(chosen, "name", name))


# =============================================================================
# Main run orchestration
# =============================================================================

# Orchestration note:
#   main() is deliberately "pipeline glue" that mirrors the build spec step-by-step.
#   It also records *all* provenance needed to reproduce a run later (hashes, versions, cache keys,
#   job ids, warnings). This verbosity is intentional: it reduces ambiguity during code review.

CSV_COLUMNS = [
    "n",
    "i",
    "j",
    "z_rest_int",
    "trial_id",
    "kappa_true",
    "kappa_hat",
    "a_true",
    "b_true",
    "cos_a_hat",
    "sin_a_hat",
    "cos_b_hat",
    "sin_b_hat",
    "amp_a",
    "amp_b",
]


def write_csv_rows(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in CSV_COLUMNS})


# Entry point (pipeline glue + provenance recorder)
# -------------------------------------------------
# The runner is designed so a reviewer can map code ↔ spec one-to-one.
# main() orchestrates:
#   - loading/validating config, model, snapshot
#   - applying strict policies (bit order, θ rule, mapping, backend mismatch)
#   - choosing contexts (exhaustive or sampled) and computing analytic targets
#   - building & (optionally) freezing transpiled circuits
#   - executing in the chosen mode and reconstructing κ̂ per context
#   - writing kappa_results.csv / counts.json / run_meta.json
#
# The long meta file is intentional: reproducibility beats convenience for κ-litmus.

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="κ-litmus qiskit_runner (Protocol B)")
    ap.add_argument("--config", type=str, required=True, help="Path to qiskit_runner.yaml")
    ap.add_argument("--dry-run", action="store_true", help="Build + transpile circuits, but do not execute")
    ap.add_argument("--validate-only", action="store_true", help="Run only preflight statevector validation, then exit")
    ap.add_argument("--skip-validation", action="store_true", help="Skip preflight statevector validation (NOT recommended)")
    ap.add_argument("--output-dir", type=str, default=None, help="Override output.dir from YAML")
    ap.add_argument("--run-id", type=str, default=None, help="Override output.run_id (or 'auto')")
    ap.add_argument("--enable-gate-noise", action="store_true", help="fake_backend: add crude depolarizing gate noise from snapshot")
    ap.add_argument("--job-timeout-s", type=float, default=None, help="qpu: per-job result timeout in seconds")
    ap.add_argument("--global-timeout-s", type=float, default=None, help="qpu: global timeout in seconds")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("--quiet", action="store_true", help="Minimal logging")

    args = ap.parse_args(list(argv) if argv is not None else None)

    start_time = datetime.now(timezone.utc)

    config_path = Path(args.config).resolve()
    cfg_dir = config_path.parent

    cfg = load_config(config_path)

    # Resolve input paths
    model_yaml_path = resolve_path(cfg_dir, cfg["model_yaml"])
    snapshot_path = resolve_path(cfg_dir, cfg["backend_snapshot_json"])

    # Resolve output directory (append backend name if not "auto")
    base_out_dir = cfg["output"]["dir"]
    backend_name_for_dir = cfg["backend"]["name"]
    if backend_name_for_dir != "auto":
        # e.g., runs_ibm -> runs_ibm_fez
        base_out_dir = f"runs_{backend_name_for_dir}"
    out_root = resolve_path(cfg_dir, base_out_dir)
    if args.output_dir is not None:
        out_root = resolve_path(cfg_dir, args.output_dir)

    # Resolve run_id (append mode suffix when auto)
    mode = cfg["mode"]
    run_id = cfg["output"]["run_id"]
    if args.run_id is not None:
        run_id = args.run_id
    if run_id == "auto":
        run_id = f"{start_time.strftime('%Y%m%d_%H%M%S')}_{mode}"

    run_dir = (out_root / str(run_id)).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    # Version and hashes
    versions = get_pkg_versions()
    model_hash = sha256_file(model_yaml_path)
    snapshot_hash = sha256_file(snapshot_path)

    warnings: List[str] = []
    errors: List[str] = []

    # Data-integrity / exit-code tracking (avoid silent corruption in hardware results)
    exit_code: int = 0
    dropped_contexts: List[Dict[str, Any]] = []

    # Load model + snapshot
    model_info = load_model_info(model_yaml_path)
    snapshot = BackendSnapshot.load(snapshot_path)

    # Apply policies
    if model_info.bit_order != cfg["policies"]["require_bit_order"]:
        raise PolicyError(
            f"bit_order mismatch: model_yaml.bit_order={model_info.bit_order!r} "
            f"!= policies.require_bit_order={cfg['policies']['require_bit_order']!r}"
        )

    mode = cfg["mode"]

    if mode in cfg["policies"]["require_physical_mapping"]["when_mode_in"]:
        if model_info.physical_qubits is None:
            raise PolicyError("physical mapping required in this mode, but model_yaml.hardware_meta.physical_qubits is missing")
        validate_physical_mapping(model_info.physical_qubits, model_info.n, snapshot)

    # Backend mismatch policy
    mismatch_policy = cfg["policies"]["model_backend_mismatch"]
    cfg_backend_name = cfg["backend"]["name"]
    snap_backend_name = snapshot.backend_name
    model_backend_name = model_info.hardware_backend

    def _handle_mismatch(msg: str) -> None:
        if mismatch_policy == "fail":
            raise PolicyError(msg)
        warnings.append(msg)

    if isinstance(cfg_backend_name, str) and cfg_backend_name != "auto":
        if cfg_backend_name != snap_backend_name:
            _handle_mismatch(f"backend mismatch: config.backend.name={cfg_backend_name!r} != snapshot.backend_name={snap_backend_name!r}")
        if model_backend_name is not None and cfg_backend_name != model_backend_name:
            _handle_mismatch(f"backend mismatch: config.backend.name={cfg_backend_name!r} != model_yaml.hardware_meta.backend={model_backend_name!r}")

    if model_backend_name is not None and model_backend_name != snap_backend_name:
        _handle_mismatch(f"backend mismatch: model_yaml.hardware_meta.backend={model_backend_name!r} != snapshot.backend_name={snap_backend_name!r}")

    # Instantiate provider
    provider = ModelProvider(model_yaml_path)

    n = provider.get_n()
    if n != model_info.n:
        warnings.append(f"provider.get_n()={n} != model_yaml.n={model_info.n}; using provider.get_n()")

    # Pair(s)
    # -------
    # Backward compatible input:
    #   protocol.pair: [i, j]
    # New input (multi‑pair in one run/job):
    #   protocol.pair: [[i, j], [k, l], ...]
    #
    # We normalize to a list of canonical (i,j) tuples (i<j).
    pairs: List[Tuple[int, int]] = normalize_protocol_pairs(cfg["protocol"]["pair"])

    # Range check now that n is known.
    for (i, j) in pairs:
        if i < 0 or j < 0 or i >= n or j >= n:
            raise ConfigError(f"protocol.pair indices out of range for n={n}: {(i, j)}")

    # Contexts
    ctx_cfg = cfg["protocol"]["context"]
    total_contexts = 1 << (n - 2)
    if ctx_cfg["mode"] == "exhaustive":
        contexts = list(range(total_contexts))
        if ctx_cfg.get("samples") is not None:
            warnings.append("protocol.context.samples is ignored because mode=='exhaustive'")
    else:
        k = int(ctx_cfg["samples"])
        seed = int(ctx_cfg["seed"])
        if k > total_contexts:
            warnings.append(f"protocol.context.samples={k} > 2^(n-2)={total_contexts}; clamping to {total_contexts}")
            k = total_contexts
        rng = random.Random(seed)
        contexts = list(range(total_contexts))
        rng.shuffle(contexts)
        contexts = sorted(contexts[:k])

    # Analytic targets (per pair)
    # --------------------------
    # NOTE: targets are derived from the *model* (diagonal_model.yaml). They are not
    # hardware truth; they serve as a convenient intended-vs-measured reference.
    targets_by_pair: Dict[Tuple[int, int], Dict[int, Targets]] = {}
    for (i, j) in pairs:
        targets_by_pair[(i, j)] = compute_targets(provider, n, i, j, contexts)

    # Build U circuit/gate
    ensure_qiskit_available()
    assert QuantumCircuit is not None

    analytic_terms = provider.get_analytic_terms()["terms"]
    terms = canonicalize_terms(analytic_terms, n)
    u_circ = build_diagonal_u_circuit(n, terms, theta_rule=cfg["policies"]["theta_rule"])
    u_gate = u_circ.to_gate(label="U")

    # Preflight validation (unless skipped)
    # ------------------------------------
    # For multi‑pair runs we validate every pair. This is cheap (few contexts in statevector)
    # and catches catastrophic convention mismatches early.
    validation_report_single: Optional[ValidationReport] = None
    validation_reports_multi: Optional[List[Dict[str, Any]]] = None
    if not args.skip_validation:
        try:
            if len(pairs) == 1:
                (i, j) = pairs[0]
                validation_report_single = preflight_validate_phasors(
                    n=n,
                    i=i,
                    j=j,
                    contexts=contexts,
                    provider=provider,
                    u_gate=u_gate,
                    tol=1e-9,
                    max_contexts=4,
                )
                if not validation_report_single.passed:
                    raise PolicyError(
                        "Preflight statevector validation failed. "
                        f"pair={(i, j)}; "
                        f"max_err_u_a={validation_report_single.max_err_u_a:g}, "
                        f"max_err_u_b={validation_report_single.max_err_u_b:g}, "
                        f"max_err_u_kappa={validation_report_single.max_err_u_kappa:g} "
                        f"(tol={validation_report_single.tol:g}). "
                        "Common causes: wrong theta sign, wrong context bit insertion, swapped i/j."
                    )
            else:
                validation_reports_multi = []
                for (i, j) in pairs:
                    rep = preflight_validate_phasors(
                        n=n,
                        i=i,
                        j=j,
                        contexts=contexts,
                        provider=provider,
                        u_gate=u_gate,
                        tol=1e-9,
                        max_contexts=4,
                    )
                    validation_reports_multi.append({"pair": [int(i), int(j)], **dataclasses.asdict(rep)})
                    if not rep.passed:
                        raise PolicyError(
                            "Preflight statevector validation failed. "
                            f"pair={(i, j)}; "
                            f"max_err_u_a={rep.max_err_u_a:g}, "
                            f"max_err_u_b={rep.max_err_u_b:g}, "
                            f"max_err_u_kappa={rep.max_err_u_kappa:g} "
                            f"(tol={rep.tol:g}). "
                            "Common causes: wrong theta sign, wrong context bit insertion, swapped i/j."
                        )
        except Exception:
            raise

    if args.validate_only:
        # Write meta and exit
        meta_path = run_dir / cfg["output"]["meta_file"]
        meta = {
            "run_id": str(run_id),
            "version": cfg["version"],
            "mode": mode,
            "start_time": start_time.isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "model_yaml": str(model_yaml_path),
            "backend_snapshot_json": str(snapshot_path),
            "hashes": {"model_yaml_sha256": model_hash, "snapshot_sha256": snapshot_hash},
            "versions": versions,
            # Single vs multi-pair are recorded differently for clarity.
            "pair": [pairs[0][0], pairs[0][1]] if len(pairs) == 1 else None,
            "pairs": [[int(i), int(j)] for (i, j) in pairs] if len(pairs) > 1 else None,
            "num_contexts_total": int(total_contexts),
            "num_contexts_used": int(len(contexts)),
            "contexts": contexts,
            "validation": (
                dataclasses.asdict(validation_report_single)
                if validation_report_single is not None
                else validation_reports_multi
            ),
            "warnings": warnings,
            "errors": errors,
            "exit_code": exit_code,
            "dropped_contexts": dropped_contexts,
            "cli_args": vars(args),
        }
        # Tidy: don't leave null placeholders in the validate-only meta output.
        if meta.get("pair") is None:
            meta.pop("pair", None)
        if meta.get("pairs") is None:
            meta.pop("pairs", None)
        meta_path.write_text(json.dumps(meta, indent=2, default=_json_default), encoding="utf-8")
        return 0
    # Build Protocol B circuits
    # ------------------------
    # We build circuits for ALL requested pairs up front, and we keep them in a
    # **context-major** order (see build_protocol_b_circuits docstring). This is
    # what enables "same job" execution for multiple pairs.
    circuits, tags = build_protocol_b_circuits(n, pairs, contexts, u_gate)

    # For qpu job splitting we treat a "context block" as atomic.
    # A context block contains all pairs' 4-setting bundles.
    circuits_per_context_block = int(len(pairs) * len(SETTINGS))

    # If statevector mode: execute immediately (no transpile needed)
    rows: List[Dict[str, Any]] = []
    counts_payload: Dict[str, Any] = {}
    jobs_meta: List[Dict[str, Any]] = []

    # Track the actually-used backend name in qpu mode (esp. when backend.name=='auto').
    # This is written to run_meta.json so post-mortems can see where the job truly ran.
    selected_backend_name: Optional[str] = None

    cache_info: Optional[FrozenCircuitsInfo] = None

    if mode == "statevector":
        if args.dry_run:
            warnings.append("dry-run has no effect in statevector mode; no transpilation/execution is performed")
            rows = []

            # Preserve legacy counts.json shape for single-pair runs.
            if len(pairs) == 1:
                (i, j) = pairs[0]
                counts_payload = {
                    "schema": "counts.v1",
                    "note": "dry-run in statevector mode; no execution",
                    "n": int(n),
                    "pair": [int(i), int(j)],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": 0,
                    "data": [],
                }
            else:
                counts_payload = {
                    "schema": "counts.v2",
                    "note": "dry-run in statevector mode (multi-pair); no execution",
                    "n": int(n),
                    "pairs": [[int(i), int(j)] for (i, j) in pairs],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": 0,
                    "data": [],
                }

        else:
            # statevector execution is naturally "single job"; for multi-pair we just
            # loop and concatenate, while keeping output schemas explicit.
            if len(pairs) == 1:
                (i, j) = pairs[0]
                rows, counts_payload = execute_statevector(
                    n,
                    i,
                    j,
                    contexts,
                    targets_by_pair[(i, j)],
                    u_gate,
                    bit_order=model_info.bit_order,
                )
            else:
                rows = []
                counts_data: List[Dict[str, Any]] = []
                for (i, j) in pairs:
                    pair_rows, pair_counts_payload = execute_statevector(
                        n,
                        i,
                        j,
                        contexts,
                        targets_by_pair[(i, j)],
                        u_gate,
                        bit_order=model_info.bit_order,
                    )
                    rows.extend(pair_rows)

                    # Annotate each entry with its pair so downstream parsing is unambiguous.
                    for ent in pair_counts_payload.get("data", []):
                        ent2 = dict(ent)
                        ent2["pair"] = [int(i), int(j)]
                        counts_data.append(ent2)

                counts_payload = {
                    "schema": "counts.v2",
                    "n": int(n),
                    "pairs": [[int(i), int(j)] for (i, j) in pairs],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": 0,
                    "data": counts_data,
                    "note": "statevector mode (multi-pair): counts are probabilities (floats), shots=0",
                }

    else:
        # Transpile (with optional freeze/reuse)
        compile_block = cfg["compile"]
        proto_sig = protocol_signature_for_cache(cfg["protocol"], contexts)
        cache_key = compute_cache_key(model_hash, snapshot_hash, compile_block, proto_sig, versions)

        cache_dir = out_root / "_cache"
        run_circuits_dir = None
        if cfg["output"]["circuits_dir"] is not None:
            run_circuits_dir = run_dir / cfg["output"]["circuits_dir"]

        reuse_allowed = bool(cfg["policies"]["freeze_transpiled_circuits"]) and (mode in cfg["policies"]["reuse_frozen_circuits"]["when_mode_in"])

        transpiled: Optional[List[QuantumCircuit]] = None
        if reuse_allowed:
            transpiled = maybe_load_frozen_circuits(cache_key, cache_dir)
            if transpiled is not None:
                cache_info = FrozenCircuitsInfo(
                    cache_key=cache_key,
                    cache_dir=cache_dir,
                    cache_qpy_path=cache_dir / f"{cache_key}.qpy",
                    cache_manifest_path=cache_dir / f"{cache_key}.json",
                    run_qpy_path=(run_circuits_dir / "transpiled.qpy") if run_circuits_dir else None,
                    run_manifest_path=(run_circuits_dir / "manifest.json") if run_circuits_dir else None,
                    reused=True,
                )
                warnings.append(f"Reused frozen transpiled circuits from cache_key={cache_key}")

        if transpiled is None:
            # Fresh transpile
            coupling = CouplingMap(snapshot.coupling_map) if CouplingMap is not None else None
            basis_gates = filter_basis_gates(snapshot.basis_gates)

            initial_layout = None
            if cfg["compile"]["layout"]["policy"] == "from_model":
                if model_info.physical_qubits is None:
                    raise PolicyError("compile.layout.policy=='from_model' but model_yaml.hardware_meta.physical_qubits is missing")
                # list[int] mapping logical -> physical
                initial_layout = list(model_info.physical_qubits)

            routing = cfg["compile"]["routing_method"]
            # Qiskit may not accept 'none' as routing_method; we handle best-effort
            routing_method = None if routing == "none" else routing

            # transpile deterministically
            transpiled = transpile(
                circuits,
                coupling_map=coupling,
                basis_gates=basis_gates,
                optimization_level=int(cfg["compile"]["optimization_level"]),
                seed_transpiler=int(cfg["compile"]["seed_transpiler"]),
                routing_method=routing_method,
                initial_layout=initial_layout,
            )

            transpiled = list(transpiled)

            if bool(cfg["policies"]["freeze_transpiled_circuits"]):
                cache_meta_preview = {
                    "compile": cfg["compile"],
                    "protocol": proto_sig,
                    "backend_name": snapshot.backend_name,
                }
                cache_info = save_frozen_circuits(transpiled, cache_key, cache_dir, run_circuits_dir, cache_meta_preview)

        if args.dry_run:
            warnings.append("dry-run: transpilation completed; skipping execution")
            rows = []

            # Preserve legacy counts.json shape for single-pair runs.
            if len(pairs) == 1:
                (i, j) = pairs[0]
                counts_payload = {
                    "schema": "counts.v1",
                    "note": "dry-run: no execution",
                    "n": int(n),
                    "pair": [int(i), int(j)],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": int(cfg["shots"]),
                    "data": [],
                }
            else:
                counts_payload = {
                    "schema": "counts.v2",
                    "note": "dry-run (multi-pair): no execution",
                    "n": int(n),
                    "pairs": [[int(i), int(j)] for (i, j) in pairs],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": int(cfg["shots"]),
                    "data": [],
                }

        else:
            # Execute transpiled circuits
            shots = int(cfg["shots"])

            if mode == "fake_backend":
                per_circuit_counts = execute_fake_backend(
                    circuits=transpiled,
                    tags=tags,
                    snapshot=snapshot,
                    shots=shots,
                    enable_gate_noise=bool(args.enable_gate_noise),
                    physical_qubits=model_info.physical_qubits,
                )

            elif mode == "qpu":
                selected_backend_name = select_backend_name(cfg, n)

                # High-risk guard: if the user configured backend.name=="auto",
                # we must ensure the selected backend is consistent with the
                # frozen snapshot/model that defines our physical mapping.
                #
                # Rationale: κ‑litmus fixes a logical→physical mapping in the model YAML
                # (hardware_meta.physical_qubits). That mapping is only meaningful on
                # the backend whose qubit indices/coupling map match the snapshot.
                #
                # If we allow auto-selection to pick a different backend, we could end up
                # running a circuit transpiled for snapshot.backend_name on a different device.
                # That is usually a silent correctness failure.
                if str(cfg["backend"]["name"]) == "auto":
                    if selected_backend_name != snap_backend_name:
                        _handle_mismatch(
                            f"backend mismatch (auto-selected): selected_backend_name={selected_backend_name!r} "
                            f"!= snapshot.backend_name={snap_backend_name!r}"
                        )
                    if model_backend_name is not None and selected_backend_name != model_backend_name:
                        _handle_mismatch(
                            f"backend mismatch (auto-selected): selected_backend_name={selected_backend_name!r} "
                            f"!= model_yaml.hardware_meta.backend={model_backend_name!r}"
                        )

                per_circuit_counts, jobs_meta = execute_qpu_batches(
                    circuits=transpiled,
                    tags=tags,
                    circuits_per_context_block=circuits_per_context_block,
                    cfg=cfg,
                    snapshot=snapshot,
                    selected_backend_name=selected_backend_name,
                    shots=shots,
                    job_timeout_s=args.job_timeout_s,
                    global_timeout_s=args.global_timeout_s,
                    max_retries=3,
                )
            else:
                raise ConfigError(f"Unhandled mode: {mode}")

            # Build counts payload
            # -------------------
            # For backward compatibility:
            #   - single-pair run: counts.v1 with top-level "pair" and per-entry WITHOUT a "pair" field
            #   - multi-pair run : counts.v2 with top-level "pairs" and per-entry WITH a "pair" field

            if len(pairs) == 1:
                (i0, j0) = pairs[0]
                data_legacy: List[Dict[str, Any]] = []
                for ent in per_circuit_counts:
                    ent2 = dict(ent)
                    ent2.pop("pair", None)
                    data_legacy.append(ent2)

                counts_payload = {
                    "schema": "counts.v1",
                    "n": int(n),
                    "pair": [int(i0), int(j0)],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": int(shots),
                    "data": data_legacy,
                }
            else:
                counts_payload = {
                    "schema": "counts.v2",
                    "n": int(n),
                    "pairs": [[int(i), int(j)] for (i, j) in pairs],
                    "bit_order": model_info.bit_order,
                    "settings": list(SETTINGS),
                    "shots_per_circuit": int(shots),
                    "data": per_circuit_counts,
                }

            # Aggregate into rows per (pair, context)
            # --------------------------------------
            # Each Protocol B κ̂ requires 4 settings for a fixed (pair, context).
            by_pair_ctx: Dict[Tuple[int, int], Dict[int, Dict[str, float]]] = {
                (int(i), int(j)): {int(z): {} for z in contexts} for (i, j) in pairs
            }

            for entry in per_circuit_counts:
                pair_list = entry.get("pair")
                if not isinstance(pair_list, list) or len(pair_list) != 2:
                    # This should never happen because CircuitTag always supplies pair.
                    raise ExecutionError(f"Malformed per-circuit entry missing pair: {entry!r}")
                pair = (int(pair_list[0]), int(pair_list[1]))

                z = int(entry["z_rest_int"])
                setting = str(entry["setting"])
                counts01 = entry["counts"]
                m, _shots_used = expectation_from_counts_01(counts01)

                if pair not in by_pair_ctx:
                    # Be robust to unexpected pairs (should not happen).
                    by_pair_ctx[pair] = {int(z2): {} for z2 in contexts}
                if z not in by_pair_ctx[pair]:
                    by_pair_ctx[pair][z] = {}
                by_pair_ctx[pair][z][setting] = float(m)

            # Emit one CSV row per (pair, context)
            for (i, j) in pairs:
                for z_rest_int in contexts:
                    z_rest_int = int(z_rest_int)

                    obs = by_pair_ctx.get((i, j), {}).get(z_rest_int, {})
                    missing = [s for s in SETTINGS if s not in obs]
                    if missing:
                        msg = (
                            f"Missing settings {missing} for pair={(i, j)} z_rest_int={z_rest_int}. "
                            "Protocol B requires all 4 settings; marking row invalid (NaN) to avoid silent corruption."
                        )
                        errors.append(msg)
                        dropped_contexts.append(
                            {
                                "pair": [int(i), int(j)],
                                "z_rest_int": int(z_rest_int),
                                "missing_settings": list(missing),
                            }
                        )
                        exit_code = max(exit_code, 2)

                        t = targets_by_pair[(i, j)][z_rest_int]
                        nan = float("nan")
                        rows.append(
                            {
                                "n": int(n),
                                "i": int(i),
                                "j": int(j),
                                "z_rest_int": int(z_rest_int),
                                "trial_id": 0,
                                "kappa_true": float(t.kappa_true),
                                "kappa_hat": nan,
                                "a_true": float(t.a_true),
                                "b_true": float(t.b_true),
                                "cos_a_hat": nan,
                                "sin_a_hat": nan,
                                "cos_b_hat": nan,
                                "sin_b_hat": nan,
                                "amp_a": nan,
                                "amp_b": nan,
                            }
                        )
                        continue

                    u_a = complex(obs["cos_a"], obs["sin_a"])
                    u_b = complex(obs["cos_b"], obs["sin_b"])
                    kappa_hat = angle_of(u_a * u_b.conjugate())

                    t = targets_by_pair[(i, j)][z_rest_int]
                    rows.append(
                        {
                            "n": int(n),
                            "i": int(i),
                            "j": int(j),
                            "z_rest_int": int(z_rest_int),
                            "trial_id": 0,
                            "kappa_true": float(t.kappa_true),
                            "kappa_hat": float(kappa_hat),
                            "a_true": float(t.a_true),
                            "b_true": float(t.b_true),
                            "cos_a_hat": float(obs["cos_a"]),
                            "sin_a_hat": float(obs["sin_a"]),
                            "cos_b_hat": float(obs["cos_b"]),
                            "sin_b_hat": float(obs["sin_b"]),
                            "amp_a": float(abs(u_a)),
                            "amp_b": float(abs(u_b)),
                        }
                    )

    # Write outputs
    kappa_file = cfg["output"]["kappa_file"]
    counts_file = cfg["output"]["counts_file"]
    meta_file = cfg["output"]["meta_file"]

    rows_path = run_dir / kappa_file
    counts_path = run_dir / counts_file
    meta_path = run_dir / meta_file

    if rows:
        write_csv_rows(rows_path, rows)
    else:
        # still create empty CSV with header for downstream stability
        write_csv_rows(rows_path, [])

    counts_path.write_text(json.dumps(counts_payload, indent=2), encoding="utf-8")

    end_time = datetime.now(timezone.utc)

    # Build run_meta.json
    meta: Dict[str, Any] = {
        "run_id": str(run_id),
        "version": cfg["version"],
        "mode": mode,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": (end_time - start_time).total_seconds(),
        "num_rows": int(len(rows)),
        "model": {
            "path": str(model_yaml_path),
            "n": int(n),
            "bit_order": model_info.bit_order,
            "hardware_backend": model_info.hardware_backend,
            "physical_qubits": model_info.physical_qubits,
            "model_yaml_sha256": model_hash,
        },
        "backend_snapshot": {
            "path": str(snapshot_path),
            "backend_name": snapshot.backend_name,
            "selected_backend_name": selected_backend_name if mode == "qpu" else None,
            "num_qubits": snapshot.num_qubits,
            "retrieved_at": snapshot.retrieved_at,
            "snapshot_sha256": snapshot_hash,
            "limits": {
                "max_experiments": snapshot.max_experiments(),
                "max_shots": snapshot.max_shots(),
            },
        },
        "protocol": {
            "name": cfg["protocol"]["name"],
            # For backward compatibility we keep the legacy field name "pair" for
            # single-pair runs. For multi-pair runs we record "pairs".
            "pair": [int(pairs[0][0]), int(pairs[0][1])] if len(pairs) == 1 else None,
            "pairs": [[int(i), int(j)] for (i, j) in pairs] if len(pairs) > 1 else None,
            "context": cfg["protocol"]["context"],
            "num_contexts_total": int(total_contexts),
            "num_contexts_used": int(len(contexts)),
            "contexts": contexts,
        },
        "output": {
            "rows_file_requested": kappa_file,
            "rows_file_effective": kappa_file,
            "counts_file": counts_file,
            "meta_file": meta_file,
            "rows_format": "csv",
        },
        "config": cfg,
        "versions": versions,
        "cache": None,
        "jobs": jobs_meta,
        "validation": (
            dataclasses.asdict(validation_report_single)
            if validation_report_single is not None
            else validation_reports_multi
        ),
        "warnings": warnings,
        "errors": errors,
        "exit_code": exit_code,
        "dropped_contexts": dropped_contexts,
        "cli_args": vars(args),
    }

    # Tidy: omit null placeholders (pair vs pairs) so run_meta.json is clean and
    # reviewer-friendly.
    proto_meta = meta.get("protocol")
    if isinstance(proto_meta, dict):
        if proto_meta.get("pair") is None:
            proto_meta.pop("pair", None)
        if proto_meta.get("pairs") is None:
            proto_meta.pop("pairs", None)

    if cache_info is not None:
        meta["cache"] = dataclasses.asdict(cache_info)

    meta_path.write_text(json.dumps(meta, indent=2, default=_json_default), encoding="utf-8")

    if not args.quiet:
        print(f"[qiskit_runner] wrote: {rows_path}")
        print(f"[qiskit_runner] wrote: {counts_path}")
        print(f"[qiskit_runner] wrote: {meta_path}")

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except RunnerError as e:
        print(f"[qiskit_runner] ERROR: {e}", file=sys.stderr)
        raise SystemExit(2)
