"""sim_runner.py

Module 2: Simulation / Measurement Runner

Reads sim_runner.yaml config and ModelProvider object,
runs Protocol B simulation with shot noise and drift,
outputs rows (CSV) + meta (json).

Architecture:
    model.yaml → Module 1 (ModelProvider) → provider object
    sim_runner.yaml → Module 2 (SimRunner)
    
    SimRunner.run(provider) → rows.csv + run_meta.json

Key design decisions:
    - Chunk-based timeline: drift and schedule operate on chunk granularity
    - Trial-wise drift reset: each trial gets fresh drift trajectory
    - Pair normalization: (i,j) → (min,max), duplicates removed
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import yaml


# =============================================================================
# Constants
# =============================================================================

SETTING_COS_A = "cos_a"
SETTING_SIN_A = "sin_a"
SETTING_COS_B = "cos_b"
SETTING_SIN_B = "sin_b"
SETTING_KEYS = (SETTING_COS_A, SETTING_SIN_A, SETTING_COS_B, SETTING_SIN_B)
NUM_SETTINGS = 4


# =============================================================================
# Exceptions
# =============================================================================

class SimRunnerError(Exception):
    """Simulation runner related errors."""
    pass


class ConfigError(SimRunnerError):
    """Configuration validation error."""
    pass


# =============================================================================
# Bitops (minimal subset, self-contained)
# =============================================================================

def sorted_pair(i: int, j: int) -> Tuple[int, int]:
    """Return a sorted (i,j) with i<j."""
    if i == j:
        raise ValueError("pair indices must be distinct")
    return (i, j) if i < j else (j, i)


def rest_positions(n: int, i: int, j: int) -> Tuple[int, ...]:
    """Return rest indices = [k for k in range(n) if k not in {i,j}]."""
    i, j = sorted_pair(i, j)
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")
    if not (0 <= i < n and 0 <= j < n):
        raise ValueError(f"pair indices out of range for n={n}: {(i, j)}")
    return tuple(k for k in range(n) if k not in (i, j))


def unpack_z_rest(z_rest_int: int, n: int, i: int, j: int) -> int:
    """Build z_base from z_rest_int by inserting context bits into full z_int."""
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


def face_vertices(z_rest_int: int, n: int, i: int, j: int) -> Tuple[int, int, int, int]:
    """Return (z00, z10, z01, z11) for the (i,j) face at context z_rest_int."""
    i, j = sorted_pair(i, j)
    z_base = unpack_z_rest(z_rest_int, n, i, j)
    z00 = z_base
    z10 = z_base ^ (1 << i)
    z01 = z_base ^ (1 << j)
    z11 = z_base ^ (1 << i) ^ (1 << j)
    return z00, z10, z01, z11


def enumerate_z_rest_ints(n: int) -> np.ndarray:
    """Enumerate all context integers z_rest_int ∈ [0, 2^(n-2))."""
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")
    return np.arange(1 << (n - 2), dtype=np.int64)


def wrap_to_pi(x: float) -> float:
    """Wrap angle to (-π, π]."""
    w = math.fmod(x + math.pi, 2 * math.pi)
    if w <= 0:
        w += 2 * math.pi
    return w - math.pi


# =============================================================================
# Config dataclasses
# =============================================================================

@dataclass
class ScanConfig:
    pair_mode: str  # "fixed" | "list" | "all"
    pairs: List[Tuple[int, int]]
    context_mode: str  # "exhaustive" | "sample"
    context_samples: Optional[int]
    context_seed: Optional[int]


@dataclass
class ShotConfig:
    enabled: bool
    shots: int


@dataclass 
class DriftConfig:
    enabled: bool
    sigma: float
    model: str
    chunk_shots: int
    hold_chunks: int
    schedule: str  # "blocked" | "interleave" | "randomize"
    schedule_seed: Optional[int]


@dataclass
class TrialsConfig:
    count: int
    seed_base: int


@dataclass
class OutputConfig:
    dir: str
    run_id: str
    rows_file: str
    meta_file: str
    # For traceability: preserve what was requested in YAML before any normalization.
    rows_file_requested: str = ""


@dataclass
class SimRunnerConfig:
    version: str
    scan: ScanConfig
    shot: ShotConfig
    drift: DriftConfig
    trials: TrialsConfig
    output: OutputConfig
    
    # Resolved at runtime
    resolved_run_id: str = ""
    resolved_output_dir: Path = field(default_factory=lambda: Path("."))


# =============================================================================
# Config loader and validator
# =============================================================================

def load_config(config_path: Union[str, Path]) -> SimRunnerConfig:
    """Load and validate sim_runner.yaml."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    
    if raw is None or not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping")
    
    return _parse_config(raw)


def _parse_config(raw: Dict[str, Any]) -> SimRunnerConfig:
    """Parse and validate config dict."""
    
    # Version
    version = raw.get("version", "sim_runner.v1")
    
    # Scan
    scan_raw = raw.get("scan", {})
    if not isinstance(scan_raw, dict):
        raise ConfigError("scan must be a mapping")
    
    pair_mode = scan_raw.get("pair_mode", "fixed")
    if pair_mode not in ("fixed", "list", "all"):
        raise ConfigError(f"scan.pair_mode must be 'fixed', 'list', or 'all', got {pair_mode!r}")
    
    pairs_raw = scan_raw.get("pairs", [[0, 1]])
    pairs = _normalize_pairs(pairs_raw)
    
    context_mode = scan_raw.get("context_mode", "exhaustive")
    if context_mode not in ("exhaustive", "sample"):
        raise ConfigError(f"scan.context_mode must be 'exhaustive' or 'sample', got {context_mode!r}")
    
    context_samples = scan_raw.get("context_samples")
    context_seed = scan_raw.get("context_seed")
    
    if context_mode == "sample":
        if context_samples is None:
            raise ConfigError("scan.context_samples required when context_mode='sample'")
        if not isinstance(context_samples, int) or context_samples < 1:
            raise ConfigError(f"scan.context_samples must be positive int, got {context_samples!r}")

        if context_seed is None:
            raise ConfigError("scan.context_seed required when context_mode='sample'")
        if not isinstance(context_seed, int) or context_seed < 0:
            raise ConfigError(f"scan.context_seed must be a non-negative int, got {context_seed!r}")
    
    scan = ScanConfig(
        pair_mode=pair_mode,
        pairs=pairs,
        context_mode=context_mode,
        context_samples=context_samples,
        context_seed=context_seed,
    )
    
    # Shot
    shot_raw = raw.get("shot", {})
    if not isinstance(shot_raw, dict):
        raise ConfigError("shot must be a mapping")
    
    shot_enabled = shot_raw.get("enabled", True)
    if not isinstance(shot_enabled, bool):
        raise ConfigError(f"shot.enabled must be bool, got {shot_enabled!r}")
    shots = shot_raw.get("shots", 1024)
    if not isinstance(shots, int) or shots < 1:
        raise ConfigError(f"shot.shots must be positive int, got {shots!r}")
    
    shot = ShotConfig(enabled=shot_enabled, shots=shots)
    
    # Drift
    drift_raw = raw.get("drift", {})
    if drift_raw is None:
        drift_raw = {}
    if not isinstance(drift_raw, dict):
        raise ConfigError("drift must be a mapping")

    drift_enabled = drift_raw.get("enabled", False)
    if not isinstance(drift_enabled, bool):
        raise ConfigError(f"drift.enabled must be bool, got {drift_enabled!r}")

    # sigma: std of drift offsets (radians), non-negative
    try:
        sigma = float(drift_raw.get("sigma", 0.0))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"drift.sigma must be a float, got {drift_raw.get('sigma')!r}") from e
    if sigma < 0.0:
        raise ConfigError(f"drift.sigma must be non-negative, got {sigma!r}")

    # FAIL-CLOSED: only one drift model is supported for now
    model = drift_raw.get("model", "piecewise_constant")
    if model != "piecewise_constant":
        raise ConfigError(f"drift.model must be 'piecewise_constant', got {model!r}")

    chunk_shots = drift_raw.get("chunk_shots", 32)
    hold_chunks = drift_raw.get("hold_chunks", 4)
    if not isinstance(chunk_shots, int) or chunk_shots < 1:
        raise ConfigError(f"drift.chunk_shots must be positive int, got {chunk_shots!r}")
    if not isinstance(hold_chunks, int) or hold_chunks < 1:
        raise ConfigError(f"drift.hold_chunks must be positive int, got {hold_chunks!r}")

    schedule = drift_raw.get("schedule", "blocked")
    if schedule not in ("blocked", "interleave", "randomize"):
        raise ConfigError(
            f"drift.schedule must be 'blocked', 'interleave', or 'randomize', got {schedule!r}"
        )

    # used only for interleave/randomize; ignored for blocked
    schedule_seed = drift_raw.get("schedule_seed")
    if schedule_seed is not None and (not isinstance(schedule_seed, int) or schedule_seed < 0):
        raise ConfigError(f"drift.schedule_seed must be a non-negative int, got {schedule_seed!r}")
    
    drift = DriftConfig(
        enabled=bool(drift_enabled),
        sigma=sigma,
        model=model,
        chunk_shots=chunk_shots,
        hold_chunks=hold_chunks,
        schedule=schedule,
        schedule_seed=schedule_seed,
    )
    
    # Trials
    trials_raw = raw.get("trials", {})
    if not isinstance(trials_raw, dict):
        raise ConfigError("trials must be a mapping")
    
    count = trials_raw.get("count", 1)
    seed_base = trials_raw.get("seed_base", 0)
    
    if not isinstance(count, int) or count < 1:
        raise ConfigError(f"trials.count must be positive int, got {count!r}")
    if not isinstance(seed_base, int):
        raise ConfigError(f"trials.seed_base must be int, got {seed_base!r}")
    
    trials = TrialsConfig(count=count, seed_base=seed_base)
    
    # Output
    output_raw = raw.get("output", {})
    if not isinstance(output_raw, dict):
        raise ConfigError("output must be a mapping")
    
    out_dir = output_raw.get("dir", "runs")
    run_id = output_raw.get("run_id", "auto")
    rows_file_req = str(output_raw.get("rows_file", "rows.csv"))
    meta_file = output_raw.get("meta_file", "run_meta.json")

    # Normalize rows_file: we only *emit* CSV.
    # - If user requested .parquet, we silently downgrade to .csv and record it in meta.
    # - If no extension is given, append .csv.
    # - Otherwise, fail-closed.
    rf_path = Path(rows_file_req)
    rf_suffix = rf_path.suffix.lower()
    if rf_suffix == "":
        rows_file = f"{rows_file_req}.csv"
    elif rf_suffix == ".csv":
        rows_file = rows_file_req
    elif rf_suffix == ".parquet":
        rows_file = str(rf_path.with_suffix(".csv"))
    else:
        raise ConfigError(
            f"output.rows_file must end with .csv (or .parquet which will be downgraded), got {rows_file_req!r}"
        )
    
    output = OutputConfig(
        dir=str(out_dir),
        run_id=str(run_id),
        rows_file=str(rows_file),
        meta_file=str(meta_file),
        rows_file_requested=rows_file_req,
    )
    
    return SimRunnerConfig(
        version=version,
        scan=scan,
        shot=shot,
        drift=drift,
        trials=trials,
        output=output,
    )


def _normalize_pairs(pairs_raw: Any) -> List[Tuple[int, int]]:
    """Normalize pairs: enforce i<j, remove duplicates."""
    if not isinstance(pairs_raw, list):
        raise ConfigError(f"scan.pairs must be a list, got {type(pairs_raw).__name__}")
    
    seen = set()
    out = []
    
    for idx, p in enumerate(pairs_raw):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ConfigError(f"scan.pairs[{idx}] must be [i, j], got {p!r}")
        
        i, j = p
        if not isinstance(i, int) or not isinstance(j, int):
            raise ConfigError(f"scan.pairs[{idx}] indices must be int, got {p!r}")
        if i == j:
            raise ConfigError(f"scan.pairs[{idx}] indices must be distinct, got {p!r}")
        
        normed = (min(i, j), max(i, j))
        if normed not in seen:
            seen.add(normed)
            out.append(normed)
    
    if len(out) == 0:
        raise ConfigError("scan.pairs must contain at least one pair")
    
    return out


# =============================================================================
# Pair expansion
# =============================================================================

def expand_pairs(config: SimRunnerConfig, n: int) -> List[Tuple[int, int]]:
    """Expand pair_mode to actual list of pairs."""
    mode = config.scan.pair_mode
    
    if mode == "fixed":
        if len(config.scan.pairs) != 1:
            raise ConfigError(
                f"pair_mode='fixed' requires exactly 1 pair, got {len(config.scan.pairs)}"
            )
        return config.scan.pairs
    
    if mode == "list":
        return config.scan.pairs
    
    if mode == "all":
        # All pairs (i,j) with i<j
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))
        return pairs
    
    raise ConfigError(f"unknown pair_mode: {mode}")


# =============================================================================
# Context handling
# =============================================================================

def get_contexts(
    config: SimRunnerConfig,
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Get context indices based on config."""
    total = 1 << (n - 2)
    
    if config.scan.context_mode == "exhaustive":
        return np.arange(total, dtype=np.int64)
    
    # sample mode
    num_samples = config.scan.context_samples
    if num_samples >= total:
        return np.arange(total, dtype=np.int64)
    
    # Sample without replacement
    # Use separate RNG seeded by context_seed for reproducibility
    ctx_rng = np.random.Generator(np.random.PCG64(config.scan.context_seed))
    return ctx_rng.choice(total, size=num_samples, replace=False).astype(np.int64)


# =============================================================================
# Seed derivation
# =============================================================================

def derive_seed(seed_base: int, trial_id: int) -> int:
    """Derive per-trial seed."""
    return seed_base + trial_id


# =============================================================================
# Schedule building (chunk-based)
# =============================================================================

def build_chunk_schedule(
    num_chunks_per_setting: int,
    schedule_type: str,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Build chunk-level schedule.
    
    Args:
        num_chunks_per_setting: number of chunks per setting
        schedule_type: "blocked" | "interleave" | "randomize"
        rng: required for "randomize"
    
    Returns:
        1D array of setting indices (0-3), length = NUM_SETTINGS * num_chunks_per_setting
    """
    total_chunks = NUM_SETTINGS * num_chunks_per_setting
    
    if schedule_type == "blocked":
        # All chunks of setting 0, then all of setting 1, etc.
        schedule = np.empty(total_chunks, dtype=np.int64)
        idx = 0
        for s in range(NUM_SETTINGS):
            schedule[idx:idx + num_chunks_per_setting] = s
            idx += num_chunks_per_setting
        return schedule
    
    if schedule_type == "interleave":
        # Round-robin: 0,1,2,3,0,1,2,3,...
        schedule = np.tile(np.arange(NUM_SETTINGS, dtype=np.int64), num_chunks_per_setting)
        return schedule
    
    if schedule_type == "randomize":
        if rng is None:
            raise SimRunnerError("rng required for randomize schedule")
        # Create balanced random permutation
        # Each setting appears exactly num_chunks_per_setting times
        chunks = []
        for s in range(NUM_SETTINGS):
            chunks.extend([s] * num_chunks_per_setting)
        chunks = np.array(chunks, dtype=np.int64)
        rng.shuffle(chunks)
        return chunks
    
    raise SimRunnerError(f"unknown schedule type: {schedule_type}")


# =============================================================================
# Drift trajectory
# =============================================================================

def sample_drift_trajectory(
    num_segments: int,
    sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample drift offsets for each segment (piecewise-constant model).
    
    Args:
        num_segments: number of drift segments
        sigma: std of drift offset (radians)
        rng: random generator
    
    Returns:
        1D array of drift offsets, length = num_segments
    """
    if sigma <= 0:
        return np.zeros(num_segments, dtype=np.float64)
    
    return rng.normal(loc=0.0, scale=sigma, size=num_segments).astype(np.float64)


# =============================================================================
# κ computation
# =============================================================================

def compute_kappa_true(
    provider,  # ModelProvider
    i: int,
    j: int,
    z_rest_int: int,
) -> Tuple[float, float, float]:
    """Compute ground-truth κ from ModelProvider.

    Returns:
        (kappa_true, a_true, b_true)
    """
    n = provider.get_n()
    z00, z10, z01, z11 = face_vertices(z_rest_int, n, i, j)

    phi00 = provider.get_diag_value(z00)
    phi10 = provider.get_diag_value(z10)
    phi01 = provider.get_diag_value(z01)
    phi11 = provider.get_diag_value(z11)

    # a = φ00 - φ01, b = φ10 - φ11
    a = phi00 - phi01
    b = phi10 - phi11
    kappa = wrap_to_pi(a - b)

    return kappa, a, b


def ideal_expectations(a: float, b: float) -> Tuple[float, float, float, float]:
    """Compute ideal expectation values for Protocol B.
    
    Returns:
        (cos_a, sin_a, cos_b, sin_b)
    """
    return (
        math.cos(a),
        math.sin(a),
        math.cos(b),
        math.sin(b),
    )


# =============================================================================
# Shot sampling
# =============================================================================

def sample_pm1_mean(
    expectation: float,
    shots: int,
    rng: np.random.Generator,
) -> float:
    """Sample mean of ±1 outcomes with given expectation.
    
    Model: P(+1) = (1+E)/2, P(-1) = (1-E)/2
    """
    if not math.isfinite(expectation):
        return float("nan")
    
    E = max(-1.0, min(1.0, expectation))
    p = 0.5 * (1.0 + E)
    k = rng.binomial(shots, p)
    return (2 * k - shots) / shots


# =============================================================================
# Protocol B estimation with chunk-based drift
# =============================================================================

@dataclass
class ProtocolBResult:
    """Result of Protocol B estimation for one (pair, context, trial)."""
    n: int
    i: int
    j: int
    z_rest_int: int
    trial_id: int
    kappa_true: float
    kappa_hat: float
    a_true: float
    b_true: float
    cos_a_hat: float
    sin_a_hat: float
    cos_b_hat: float
    sin_b_hat: float
    amp_a: float
    amp_b: float


def run_protocol_b_chunked(
    provider,  # ModelProvider
    i: int,
    j: int,
    z_rest_int: int,
    trial_id: int,
    config: SimRunnerConfig,
    schedule: np.ndarray,
    drift_trajectory: np.ndarray,
    rng: np.random.Generator,
) -> ProtocolBResult:
    """Run Protocol B with chunk-based execution.
    
    Args:
        provider: ModelProvider object
        i, j: pair indices
        z_rest_int: context
        trial_id: trial index
        config: simulation config
        schedule: chunk-level schedule (setting indices)
        drift_trajectory: drift offset per segment
        rng: random generator
    
    Returns:
        ProtocolBResult
    """
    n = provider.get_n()
    
    # Ground truth
    kappa_true, a_true, b_true = compute_kappa_true(provider, i, j, z_rest_int)
    
    # Ideal expectations (no noise)
    cos_a_ideal, sin_a_ideal, cos_b_ideal, sin_b_ideal = ideal_expectations(a_true, b_true)
    
    if not config.shot.enabled and not config.drift.enabled:
        # No noise: return ideal
        kappa_hat = kappa_true
        u_a = complex(cos_a_ideal, sin_a_ideal)
        u_b = complex(cos_b_ideal, sin_b_ideal)
        return ProtocolBResult(
            n=n, i=i, j=j, z_rest_int=z_rest_int, trial_id=trial_id,
            kappa_true=kappa_true, kappa_hat=kappa_hat,
            a_true=a_true, b_true=b_true,
            cos_a_hat=cos_a_ideal, sin_a_hat=sin_a_ideal,
            cos_b_hat=cos_b_ideal, sin_b_hat=sin_b_ideal,
            amp_a=abs(u_a), amp_b=abs(u_b),
        )
    
    # With noise: chunk-based execution
    chunk_shots = config.drift.chunk_shots
    hold_chunks = config.drift.hold_chunks
    shots_per_setting = config.shot.shots
    
    # Number of chunks per setting
    num_chunks_per_setting = (shots_per_setting + chunk_shots - 1) // chunk_shots
    
    # Accumulate outcomes per setting
    # outcomes[s] = list of (shot_count, sum_of_outcomes)
    outcomes = {s: [] for s in range(NUM_SETTINGS)}
    
    # Map setting index to ideal expectation and phase
    setting_ideals = {
        0: cos_a_ideal,  # cos_a
        1: sin_a_ideal,  # sin_a
        2: cos_b_ideal,  # cos_b
        3: sin_b_ideal,  # sin_b
    }
    setting_phases = {
        0: a_true,  # cos(a)
        1: a_true,  # sin(a)
        2: b_true,  # cos(b)
        3: b_true,  # sin(b)
    }
    setting_is_sin = {0: False, 1: True, 2: False, 3: True}
    
    # Track how many shots each setting has received
    shots_received = {s: 0 for s in range(NUM_SETTINGS)}
    
    for chunk_idx, setting in enumerate(schedule):
        setting = int(setting)
        
        # Check if this setting still needs shots
        if shots_received[setting] >= shots_per_setting:
            continue
        
        # Determine actual shots for this chunk
        remaining = shots_per_setting - shots_received[setting]
        actual_chunk_shots = min(chunk_shots, remaining)
        
        # Get drift offset for this chunk
        if config.drift.enabled:
            segment_idx = chunk_idx // hold_chunks
            segment_idx = min(segment_idx, len(drift_trajectory) - 1)
            drift_offset = drift_trajectory[segment_idx]
        else:
            drift_offset = 0.0
        
        # Compute expectation with drift
        phase = setting_phases[setting]
        is_sin = setting_is_sin[setting]
        
        if is_sin:
            E_noisy = math.sin(phase + drift_offset)
        else:
            E_noisy = math.cos(phase + drift_offset)
        
        # Shot sampling
        if config.shot.enabled:
            E_measured = sample_pm1_mean(E_noisy, actual_chunk_shots, rng)
        else:
            E_measured = E_noisy
        
        outcomes[setting].append((actual_chunk_shots, E_measured * actual_chunk_shots))
        shots_received[setting] += actual_chunk_shots
    
    # Aggregate outcomes per setting
    def aggregate(setting: int) -> float:
        total_shots = 0
        total_sum = 0.0
        for (ns, s) in outcomes[setting]:
            total_shots += ns
            total_sum += s
        if total_shots == 0:
            return 0.0
        return total_sum / total_shots
    
    cos_a_hat = aggregate(0)
    sin_a_hat = aggregate(1)
    cos_b_hat = aggregate(2)
    sin_b_hat = aggregate(3)
    
    # Estimate κ using phasor method
    u_a = complex(cos_a_hat, sin_a_hat)
    u_b = complex(cos_b_hat, sin_b_hat)
    amp_a = abs(u_a)
    amp_b = abs(u_b)
    u_kappa = u_a * np.conj(u_b)
    kappa_hat = float(np.angle(u_kappa))

    return ProtocolBResult(
        n=n, i=i, j=j, z_rest_int=z_rest_int, trial_id=trial_id,
        kappa_true=kappa_true, kappa_hat=kappa_hat,
        a_true=a_true, b_true=b_true,
        cos_a_hat=cos_a_hat, sin_a_hat=sin_a_hat,
        cos_b_hat=cos_b_hat, sin_b_hat=sin_b_hat,
        amp_a=amp_a, amp_b=amp_b,
    )


# =============================================================================
# Row building
# =============================================================================

def result_to_row(result: ProtocolBResult) -> Dict[str, Any]:
    """Convert ProtocolBResult to row dict."""
    return {
        "n": result.n,
        "i": result.i,
        "j": result.j,
        "z_rest_int": result.z_rest_int,
        "trial_id": result.trial_id,
        "kappa_true": result.kappa_true,
        "kappa_hat": result.kappa_hat,
        "a_true": result.a_true,
        "b_true": result.b_true,
        "cos_a_hat": result.cos_a_hat,
        "sin_a_hat": result.sin_a_hat,
        "cos_b_hat": result.cos_b_hat,
        "sin_b_hat": result.sin_b_hat,
        "amp_a": result.amp_a,
        "amp_b": result.amp_b,
    }

# =============================================================================
# I/O
# =============================================================================

def save_rows(rows: List[Dict[str, Any]], output_path: Path) -> None:
    """Save rows to CSV.

    Notes:
      - Parquet is intentionally not used (to avoid pyarrow dependency).
      - If the caller passes a .parquet path, we silently downgrade to .csv.
    """
    if len(rows) == 0:
        raise SimRunnerError("no rows to save")

    suffix = output_path.suffix.lower()
    if suffix == "":
        output_path = output_path.with_name(output_path.name + ".csv")
    elif suffix == ".parquet":
        output_path = output_path.with_suffix(".csv")
    elif suffix != ".csv":
        raise SimRunnerError(
            f"unsupported rows_file extension: {suffix!r} (use .csv; .parquet will be downgraded to .csv)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    import csv
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def save_meta(
    config: SimRunnerConfig,
    provider,  # ModelProvider
    output_path: Path,
    start_time: datetime,
    end_time: datetime,
    num_rows: int,
    resolved_pairs: List[Tuple[int, int]],
    num_contexts_total: int,
    num_contexts_used: int,
) -> None:
    """Save run metadata to JSON."""
    # Scan meta: preserve requested config, but also record what was actually used.
    scan_meta: Dict[str, Any] = {
        "pair_mode": config.scan.pair_mode,
        "pairs": config.scan.pairs,
        "resolved_pairs": [list(p) for p in resolved_pairs],
        "num_pairs_used": int(len(resolved_pairs)),
        "context_mode": config.scan.context_mode,
        "num_contexts_total": int(num_contexts_total),
        "num_contexts_used": int(num_contexts_used),
        # Filled below depending on context_mode
        "context_samples": config.scan.context_samples,
        "context_seed": config.scan.context_seed,
    }

    # If exhaustive, context_samples/context_seed are *ignored* even if present in YAML.
    if config.scan.context_mode == "exhaustive":
        scan_meta["context_params_ignored_in_exhaustive"] = {
            "ignored": bool(config.scan.context_samples is not None or config.scan.context_seed is not None),
            "context_samples_requested": config.scan.context_samples,
            "context_seed_requested": config.scan.context_seed,
        }
        scan_meta["context_samples"] = None
        scan_meta["context_seed"] = None
    else:
        scan_meta["context_params_ignored_in_exhaustive"] = {"ignored": False}

    meta: Dict[str, Any] = {
        "run_id": config.resolved_run_id,
        "version": config.version,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": (end_time - start_time).total_seconds(),
        "num_rows": num_rows,
        "model": {
            "n": provider.get_n(),
        },
        "output": {
            "rows_file_requested": config.output.rows_file_requested or config.output.rows_file,
            "rows_file_effective": config.output.rows_file,
            "meta_file": config.output.meta_file,
            "rows_format": "csv",
        },
        "config": {
            "scan": scan_meta,
            "shot": {
                "enabled": config.shot.enabled,
                "shots": config.shot.shots,
            },
            "drift": {
                "enabled": config.drift.enabled,
                "sigma": config.drift.sigma,
                "model": config.drift.model,
                "chunk_shots": config.drift.chunk_shots,
                "hold_chunks": config.drift.hold_chunks,
                "schedule": config.drift.schedule,
                "schedule_seed": config.drift.schedule_seed,
            },
            "trials": {
                "count": config.trials.count,
                "seed_base": config.trials.seed_base,
            },
        },
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# =============================================================================
# Main runner
# =============================================================================

class SimRunner:
    """Simulation runner."""
    
    def __init__(self, config: SimRunnerConfig):
        self.config = config
    
    @classmethod
    def from_yaml(cls, config_path: Union[str, Path]) -> "SimRunner":
        """Create runner from YAML config file."""
        config = load_config(config_path)
        return cls(config)
    
    def run(self, provider) -> Path:
        """Run simulation and save results.
        
        Args:
            provider: ModelProvider object
        
        Returns:
            Path to output directory
        """
        start_time = datetime.now(timezone.utc)
        
        n = provider.get_n()
        config = self.config
        
        # Resolve run_id
        if config.output.run_id == "auto":
            config.resolved_run_id = start_time.strftime("%Y%m%d_%H%M%S")
        else:
            config.resolved_run_id = config.output.run_id
        
        # Resolve output directory
        config.resolved_output_dir = Path(config.output.dir) / config.resolved_run_id
        config.resolved_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Expand pairs
        pairs = expand_pairs(config, n)
        
        # Validate pairs against n
        for (i, j) in pairs:
            if i < 0 or i >= n or j < 0 or j >= n:
                raise SimRunnerError(f"pair ({i},{j}) out of range for n={n}")
        
        # Compute schedule parameters
        shots_per_setting = config.shot.shots
        chunk_shots = config.drift.chunk_shots
        hold_chunks = config.drift.hold_chunks
        
        num_chunks_per_setting = (shots_per_setting + chunk_shots - 1) // chunk_shots
        total_chunks = NUM_SETTINGS * num_chunks_per_setting
        num_segments = (total_chunks + hold_chunks - 1) // hold_chunks
        
        # Main loop
        rows = []

        # ------------------------------------------------------------
        # Build chunk schedule ONCE (fixed across trials)
        # ------------------------------------------------------------
        schedule_rng_fixed = None
        if config.drift.schedule == "randomize":
            sched_seed = config.drift.schedule_seed
            if sched_seed is None:
                # fixed default seed (does not depend on trial_id)
                sched_seed = config.trials.seed_base + 1_000_000
            schedule_rng_fixed = np.random.Generator(np.random.PCG64(int(sched_seed)))

        schedule_fixed = build_chunk_schedule(
            num_chunks_per_setting,
            config.drift.schedule,
            schedule_rng_fixed,
        )

        # ------------------------------------------------------------
        # Contexts fixed across trials
        # - exhaustive: always all contexts
        # - sample: determined solely by scan.context_seed
        # ------------------------------------------------------------
        seed0 = derive_seed(config.trials.seed_base, 0)
        rng0 = np.random.Generator(np.random.PCG64(seed0))
        contexts = get_contexts(config, n, rng0)

        for trial_id in range(config.trials.count):
            seed = derive_seed(config.trials.seed_base, trial_id)
            rng = np.random.Generator(np.random.PCG64(seed))

            # Sample drift trajectory (reset each trial)
            if config.drift.enabled:
                drift_trajectory = sample_drift_trajectory(num_segments, config.drift.sigma, rng)
            else:
                drift_trajectory = np.zeros(num_segments, dtype=np.float64)

            schedule = schedule_fixed

            for (i, j) in pairs:
                for z_rest_int in contexts:
                    result = run_protocol_b_chunked(
                        provider=provider,
                        i=i,
                        j=j,
                        z_rest_int=int(z_rest_int),
                        trial_id=trial_id,
                        config=config,
                        schedule=schedule,
                        drift_trajectory=drift_trajectory,
                        rng=rng,
                    )
                    rows.append(result_to_row(result))
        
        end_time = datetime.now(timezone.utc)
        
        # Save outputs
        rows_path = config.resolved_output_dir / config.output.rows_file
        meta_path = config.resolved_output_dir / config.output.meta_file
        
        save_rows(rows, rows_path)
        save_meta(
            config=config,
            provider=provider,
            output_path=meta_path,
            start_time=start_time,
            end_time=end_time,
            num_rows=len(rows),
            resolved_pairs=pairs,
            num_contexts_total=(1 << (n - 2)),
            num_contexts_used=int(len(contexts)),
        )
        
        return config.resolved_output_dir


# =============================================================================
# CLI entry point
# =============================================================================

def main():
    """Command-line entry point."""
    import argparse
    import sys
    
    # Import ModelProvider (assumed to be in same directory or installed)
    try:
        from model_provider import ModelProvider
    except ImportError:
        print("Error: model_provider.py not found", file=sys.stderr)
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description="Run κ-litmus simulation")
    parser.add_argument("--model", required=True, help="Path to diagonal_model.yaml")
    parser.add_argument("--config", required=True, help="Path to sim_runner.yaml")
    args = parser.parse_args()
    
    provider = ModelProvider(args.model)
    runner = SimRunner.from_yaml(args.config)
    output_dir = runner.run(provider)
    
    print(f"Done. Output: {output_dir}")


if __name__ == "__main__":
    main()