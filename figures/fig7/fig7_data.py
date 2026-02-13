# fig7_data.py
#
# Appendix Fig. 7: Drift / schedule ablation (blocked vs interleaved settings)
#
# Data stage only: load counts + run_meta, compute point estimates and
# shot-bootstrap uncertainty (percentile CI).
#
# Alignment with Fig.5 philosophy:
#   - point estimator defaults to bootstrap median (keeps point inside percentile CI)
#   - CI is represented as [ci_lo, ci_hi] and plotted as whiskers (not symmetric ±)
#
# Plotting is intentionally separated into fig7_plot.py.

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Constants / circular stats
# -----------------------------------------------------------------------------

SETTINGS: Tuple[str, str, str, str] = ("cos_a", "sin_a", "cos_b", "sin_b")


def wrap_to_pi(angle_rad: np.ndarray) -> np.ndarray:
    """Wrap angles to (-pi, pi]."""
    return (angle_rad + np.pi) % (2 * np.pi) - np.pi


def circ_mean(angles_rad: np.ndarray) -> float:
    """Circular mean angle in radians (principal value)."""
    angles = np.asarray(angles_rad, float)
    angles = angles[np.isfinite(angles)]
    if angles.size == 0:
        return float("nan")
    z = np.mean(np.exp(1j * angles))
    return float(np.angle(z))


def circ_resultant_length(angles_rad: np.ndarray) -> float:
    """Resultant length R = |mean(exp(i*theta))| in [0,1]."""
    angles = np.asarray(angles_rad, float)
    angles = angles[np.isfinite(angles)]
    if angles.size == 0:
        return float("nan")
    z = np.mean(np.exp(1j * angles))
    return float(np.abs(z))


# -----------------------------------------------------------------------------
# Config + run metadata containers
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class fig7AnalysisConfig:
    """Analysis hyperparameters and run ordering for Fig.S1."""

    # Which run segments we prefer to show on the x-axis (filtered to those present).
    run_order_plot: Tuple[str, ...] = ("I1", "I2", "B", "I3", "I4", "I_sum")

    # Optional aggregates
    include_I12: bool = True
    include_I34: bool = True
    include_I_sum: bool = True

    # Quality summary metric (used in panel B)
    amp_min_quantile: float = 0.10

    # Shot-bootstrap UQ (raw-count bootstrap)
    boot_B: int = 5000
    seed: int = 12345
    ci_levels: Tuple[float, float] = (0.025, 0.975)

    # Point estimate shown in the figure.
    # - "trial": compute directly from observed counts
    # - "boot_median": use the bootstrap median (default; keeps point within percentile CI)
    # - "boot_mean": use the bootstrap mean
    point_estimator: str = "boot_median"


@dataclass(frozen=True)
class RunInfo:
    """Lightweight run descriptor extracted from counts + run_meta."""

    run_label: str
    shots_per_circuit: int
    n: int
    pairs: List[Tuple[int, int]]
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    schedule_mode: Optional[str] = None


# -----------------------------------------------------------------------------
# I/O helpers
# -----------------------------------------------------------------------------


def file_sha256(path: Path, blocksize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(blocksize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def stable_int_seed(base_seed: int, key: str) -> int:
    """Deterministic per-group seed (mirrors Fig.5 tooling)."""
    h = hashlib.sha256(f"{base_seed}:{key}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % (2**32)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------------------------------------------------------------
# Loading counts.v2 into long-form rows
# -----------------------------------------------------------------------------


def counts_v2_to_rows(counts_payload: Dict[str, Any], run_label: str) -> pd.DataFrame:
    """Convert a counts.v2 payload into a long DataFrame (one row per circuit)."""
    if counts_payload.get("schema") != "counts.v2":
        raise ValueError(
            f"{run_label}: expected schema 'counts.v2', got {counts_payload.get('schema')!r}"
        )

    n = int(counts_payload["n"])
    pairs = [tuple(p) for p in counts_payload["pairs"]]
    settings = tuple(counts_payload["settings"])
    if settings != SETTINGS:
        raise ValueError(f"{run_label}: unexpected settings={settings!r}; expected {SETTINGS!r}")

    rows: List[Dict[str, Any]] = []
    for rec in counts_payload.get("data", []):
        pair = tuple(rec["pair"])
        if pair not in pairs:
            raise ValueError(f"{run_label}: found pair {pair} not declared in top-level pairs={pairs}")

        setting = str(rec["setting"])
        if setting not in SETTINGS:
            raise ValueError(f"{run_label}: unknown setting {setting!r}")

        shots = int(rec.get("shots", counts_payload.get("shots_per_circuit", 0)))
        c0 = int(rec["counts"].get("0", 0))
        c1 = int(rec["counts"].get("1", 0))
        if shots <= 0:
            shots = c0 + c1

        rows.append(
            {
                "run_label": run_label,
                "n": n,
                "pair": f"({pair[0]},{pair[1]})",
                "i": int(pair[0]),
                "j": int(pair[1]),
                "z_rest_int": int(rec["z_rest_int"]),
                "setting": setting,
                "shots": int(shots),
                "c0": int(c0),
                "c1": int(c1),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{run_label}: empty counts payload (no 'data' rows)")
    return df


def _mode_int(s: pd.Series) -> int:
    """Stable integer mode (falls back to first element)."""
    m = s.mode(dropna=True)
    if len(m) == 0:
        return int(s.iloc[0])
    return int(m.iloc[0])


def load_block(block_counts_path: Path, block_meta_path: Path, run_label: str = "B") -> Tuple[pd.DataFrame, RunInfo]:
    counts_payload = load_json(block_counts_path)
    meta = load_json(block_meta_path)

    df = counts_v2_to_rows(counts_payload, run_label=run_label)
    shots_per_circuit = int(counts_payload.get("shots_per_circuit", _mode_int(df["shots"])))

    info = RunInfo(
        run_label=run_label,
        shots_per_circuit=shots_per_circuit,
        n=int(counts_payload["n"]),
        pairs=[tuple(p) for p in counts_payload["pairs"]],
        start_time=meta.get("start_time"),
        end_time=meta.get("end_time"),
        schedule_mode=meta.get("schedule", {}).get("mode"),
    )
    return df, info


def load_interleave(
    interleave_counts_path: Path,
    interleave_meta_path: Path,
    label_prefix: str = "I",
) -> Tuple[pd.DataFrame, List[RunInfo]]:
    """Load interleaved schedule input (list-of-segments JSON)."""
    counts_list = load_json(interleave_counts_path)
    meta_list = load_json(interleave_meta_path)

    if not isinstance(counts_list, list) or not isinstance(meta_list, list):
        raise ValueError("Interleave inputs must be JSON lists (segments).")

    meta_by_number: Dict[int, Dict[str, Any]] = {}
    for seg in meta_list:
        num = int(seg.get("number"))
        meta_by_number[num] = seg.get("data", {})

    dfs: List[pd.DataFrame] = []
    infos: List[RunInfo] = []
    for seg in counts_list:
        num = int(seg.get("number"))
        run_label = f"{label_prefix}{num}"
        counts_payload = seg.get("data", {})

        df_seg = counts_v2_to_rows(counts_payload, run_label=run_label)
        dfs.append(df_seg)

        meta = meta_by_number.get(num, {})
        shots_per_circuit = int(counts_payload.get("shots_per_circuit", _mode_int(df_seg["shots"])))
        infos.append(
            RunInfo(
                run_label=run_label,
                shots_per_circuit=shots_per_circuit,
                n=int(counts_payload["n"]),
                pairs=[tuple(p) for p in counts_payload["pairs"]],
                start_time=meta.get("start_time"),
                end_time=meta.get("end_time"),
                schedule_mode="interleave",
            )
        )

    df_all = pd.concat(dfs, ignore_index=True)

    def _sort_key(ri: RunInfo) -> int:
        try:
            return int(ri.run_label[len(label_prefix) :])
        except Exception:
            return 10**9

    infos = sorted(infos, key=_sort_key)
    return df_all, infos


# -----------------------------------------------------------------------------
# Derivations: context-level κ̂ (trial) and per-run summary (trial)
# -----------------------------------------------------------------------------


def add_expectations(df_counts: pd.DataFrame) -> pd.DataFrame:
    """Add expectation value per circuit: <Z> = (c0 - c1) / shots."""
    df = df_counts.copy()
    df["exp"] = (df["c0"] - df["c1"]) / df["shots"].astype(float)
    return df


def derive_context_kappa(df_counts: pd.DataFrame) -> pd.DataFrame:
    """Compute context-level phasors and κ̂ for each run segment (trial)."""
    df = add_expectations(df_counts)

    piv = (
        df.pivot_table(
            index=["run_label", "n", "pair", "i", "j", "z_rest_int"],
            columns="setting",
            values="exp",
            aggfunc="mean",
        )
        .reset_index()
        .copy()
    )

    for s in SETTINGS:
        if s not in piv.columns:
            piv[s] = np.nan

    u_a = piv["cos_a"].to_numpy(float) + 1j * piv["sin_a"].to_numpy(float)
    u_b = piv["cos_b"].to_numpy(float) + 1j * piv["sin_b"].to_numpy(float)

    piv["amp_a"] = np.abs(u_a)
    piv["amp_b"] = np.abs(u_b)
    piv["amp_min"] = np.minimum(piv["amp_a"], piv["amp_b"])
    piv["kappa_hat"] = wrap_to_pi(np.angle(u_a * np.conj(u_b)))
    piv["kappa_deg"] = np.degrees(piv["kappa_hat"])

    shots_mode = df.groupby("run_label")["shots"].agg(_mode_int)
    piv["shots_per_circuit"] = piv["run_label"].map(shots_mode)

    return piv


def derive_summary_metrics(df_ctx: pd.DataFrame, amp_min_quantile: float = 0.10) -> pd.DataFrame:
    """Summarize κ-profile dispersion + quality per (run_label, pair) (trial)."""
    rows: List[Dict[str, Any]] = []
    for (run_label, pair), grp in df_ctx.groupby(["run_label", "pair"], sort=False):
        n = int(grp["n"].iloc[0])
        i = int(grp["i"].iloc[0])
        j = int(grp["j"].iloc[0])
        angles = grp["kappa_hat"].to_numpy(float)
        R = circ_resultant_length(angles)
        V = float("nan") if not math.isfinite(R) else float(np.clip(1.0 - R, 0.0, 1.0))
        amp = grp["amp_min"].to_numpy(float)
        rows.append(
            {
                "run_label": run_label,
                "n": n,
                "i": i,
                "j": j,
                "pair": pair,
                "shots_per_circuit": int(grp["shots_per_circuit"].iloc[0]),
                "V_circ": V,
                "R": float(R),
                "circ_mean_rad": circ_mean(angles),
                "circ_mean_deg": float(np.degrees(circ_mean(angles))),
                "amp_min_mean": float(np.nanmean(amp)),
                "amp_min_q10": float(np.nanquantile(amp, amp_min_quantile)),
            }
        )
    return pd.DataFrame(rows)


def aggregate_runs(df_counts: pd.DataFrame, run_labels: List[str], new_label: str) -> pd.DataFrame:
    """Sum counts over a subset of run_labels to build an aggregated run."""
    sub = df_counts[df_counts["run_label"].isin(run_labels)].copy()
    if sub.empty:
        raise ValueError(f"aggregate_runs: no rows for run_labels={run_labels}")

    gcols = ["n", "pair", "i", "j", "z_rest_int", "setting"]
    agg = (
        sub.groupby(gcols, as_index=False)
        .agg(
            shots=("shots", "sum"),
            c0=("c0", "sum"),
            c1=("c1", "sum"),
        )
        .copy()
    )
    agg.insert(0, "run_label", new_label)
    return agg


# -----------------------------------------------------------------------------
# Shot-bootstrap for (run_label, pair)
# -----------------------------------------------------------------------------


def _build_shots_c0_arrays(counts_df_group: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """Return shots[C,4], c0[C,4], contexts list. Robust to duplicates by summing."""
    # Sum duplicates (if any) to define a single binomial parameter per (context,setting).
    g = (
        counts_df_group.groupby(["z_rest_int", "setting"], as_index=False)
        .agg(shots=("shots", "sum"), c0=("c0", "sum"))
        .copy()
    )
    contexts = sorted(g["z_rest_int"].unique().tolist())
    ctx_idx = {z: k for k, z in enumerate(contexts)}
    s_idx = {s: k for k, s in enumerate(SETTINGS)}

    C = len(contexts)
    shots = np.zeros((C, 4), dtype=int)
    c0 = np.zeros((C, 4), dtype=int)

    for r in g.itertuples(index=False):
        ci = ctx_idx[int(r.z_rest_int)]
        si = s_idx[str(r.setting)]
        shots[ci, si] = int(r.shots)
        c0[ci, si] = int(r.c0)

    return shots, c0, contexts


def bootstrap_run_pair_metrics(
    counts_df_group: pd.DataFrame,
    cfg: fig7AnalysisConfig,
    *,
    trial_id: int = 0,
    amp_min_quantile: float = 0.10,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, float], Dict[str, float], Dict[str, Any]]:
    """Shot bootstrap for V_circ and q10(amp_min) for one (run_label,n,i,j) group."""

    run_label = str(counts_df_group["run_label"].iloc[0])
    n = int(counts_df_group["n"].iloc[0])
    i = int(counts_df_group["i"].iloc[0])
    j = int(counts_df_group["j"].iloc[0])

    shots, c0, contexts = _build_shots_c0_arrays(counts_df_group)
    C = len(contexts)
    has_all = np.all(shots > 0, axis=1)

    # Point (trial) mask: keep contexts with all settings and finite kappa.
    shots_f = shots.astype(float)
    m_point = np.where(shots_f > 0, (2.0 * c0 - shots_f) / shots_f, np.nan)
    ua_point = m_point[:, 0] + 1j * m_point[:, 1]
    ub_point = m_point[:, 2] + 1j * m_point[:, 3]
    kappa_point = np.angle(ua_point * np.conj(ub_point))
    base_mask = has_all & np.isfinite(kappa_point)

    group_seed = stable_int_seed(cfg.seed, f"run={run_label},n={n},i={i},j={j},trial={trial_id}")
    rng = np.random.default_rng(group_seed)

    # Binomial parameters
    p0 = np.divide(c0, shots, out=np.zeros_like(c0, dtype=float), where=shots > 0)
    c0_bs = rng.binomial(n=shots, p=p0, size=(cfg.boot_B,) + shots.shape)  # (B,C,4)

    # Expectation values per bootstrap
    shots_f_bs = shots.astype(float)
    m = np.where(shots_f_bs > 0, (2.0 * c0_bs - shots_f_bs) / shots_f_bs, np.nan)

    ua = m[:, :, 0] + 1j * m[:, :, 1]
    ub = m[:, :, 2] + 1j * m[:, :, 3]
    kappa = np.angle(ua * np.conj(ub))  # (B,C)

    mask = np.broadcast_to(base_mask, (cfg.boot_B, C))

    # V_circ bootstrap distribution
    ph = np.exp(1j * kappa)
    sum_ph = (ph * mask).sum(axis=1)
    cnt = mask.sum(axis=1)
    mean_ph = np.where(cnt > 0, sum_ph / cnt, np.nan + 1j * np.nan)
    V = 1.0 - np.abs(mean_ph)
    V = np.clip(V, 0.0, 1.0)
    V[cnt == 0] = np.nan

    # q10(amp_min) bootstrap distribution
    amp_a = np.sqrt(m[:, :, 0] ** 2 + m[:, :, 1] ** 2)
    amp_b = np.sqrt(m[:, :, 2] ** 2 + m[:, :, 3] ** 2)
    amp_min = np.minimum(amp_a, amp_b)  # (B,C)
    amp_min_masked = np.where(mask, amp_min, np.nan)
    amp_q = np.nanquantile(amp_min_masked, amp_min_quantile, axis=1)

    lo, hi = cfg.ci_levels
    summ_V = dict(
        mean=float(np.nanmean(V)),
        median=float(np.nanmedian(V)),
        std=float(np.nanstd(V, ddof=1)),
        ci_lo=float(np.nanquantile(V, lo)),
        ci_hi=float(np.nanquantile(V, hi)),
        boot_empty_frac=float(np.mean(cnt == 0)),
        num_contexts_used=int(np.sum(base_mask)),
        group_seed=int(group_seed),
    )
    summ_A = dict(
        mean=float(np.nanmean(amp_q)),
        median=float(np.nanmedian(amp_q)),
        std=float(np.nanstd(amp_q, ddof=1)),
        ci_lo=float(np.nanquantile(amp_q, lo)),
        ci_hi=float(np.nanquantile(amp_q, hi)),
        boot_empty_frac=float(np.mean(~np.isfinite(amp_q))),
        num_contexts_used=int(np.sum(base_mask)),
        group_seed=int(group_seed),
    )

    debug = {
        "contexts": contexts,
        "base_mask": base_mask.tolist(),
    }
    return V, amp_q, summ_V, summ_A, debug


# -----------------------------------------------------------------------------
# High-level builder
# -----------------------------------------------------------------------------


def compute_fig7_products(
    *,
    interleave_counts_json: Path,
    interleave_meta_json: Path,
    block_counts_json: Path,
    block_meta_json: Path,
    cfg: fig7AnalysisConfig | None = None,
) -> Dict[str, Any]:
    """Compute all Fig.S1 data products."""

    if cfg is None:
        cfg = fig7AnalysisConfig()

    # Load
    df_I, infos_I = load_interleave(interleave_counts_json, interleave_meta_json, label_prefix="I")
    df_B, info_B = load_block(block_counts_json, block_meta_json, run_label="B")

    # Optional aggregates
    frames: List[pd.DataFrame] = [df_I, df_B]
    present_I = set(df_I["run_label"].unique())

    if cfg.include_I12 and {"I1", "I2"}.issubset(present_I):
        frames.append(aggregate_runs(df_I, ["I1", "I2"], "I12"))
    if cfg.include_I34 and {"I3", "I4"}.issubset(present_I):
        frames.append(aggregate_runs(df_I, ["I3", "I4"], "I34"))
    if cfg.include_I_sum:
        I_labels = sorted(
            df_I["run_label"].unique(),
            key=lambda s: int(s[1:]) if s.startswith("I") and s[1:].isdigit() else 10**9,
        )
        frames.append(aggregate_runs(df_I, I_labels, "I_sum"))

    df_counts_all = pd.concat(frames, ignore_index=True)

    # Trial context table + trial summary
    df_ctx = derive_context_kappa(df_counts_all)
    df_sum_trial = derive_summary_metrics(df_ctx, amp_min_quantile=cfg.amp_min_quantile)

    # Shot-bootstrap summaries (per run_label, pair)
    boot_rows: List[Dict[str, Any]] = []
    boot_debug: Dict[str, Any] = {}
    for (run_label, n, i, j), g in df_counts_all.groupby(["run_label", "n", "i", "j"], sort=False):
        V_boot, A_boot, sV, sA, dbg = bootstrap_run_pair_metrics(
            g,
            cfg,
            trial_id=0,
            amp_min_quantile=cfg.amp_min_quantile,
        )
        boot_rows.append(
            dict(
                run_label=str(run_label),
                n=int(n),
                i=int(i),
                j=int(j),
                pair=f"({int(i)},{int(j)})",
                # V_circ
                V_circ_ci95_lo=float(sV["ci_lo"]),
                V_circ_ci95_hi=float(sV["ci_hi"]),
                V_circ_shotbs_mean=float(sV["mean"]),
                V_circ_shotbs_median=float(sV["median"]),
                V_circ_shotbs_std=float(sV["std"]),
                # amp_min q10
                amp_min_q10_ci95_lo=float(sA["ci_lo"]),
                amp_min_q10_ci95_hi=float(sA["ci_hi"]),
                amp_min_q10_shotbs_mean=float(sA["mean"]),
                amp_min_q10_shotbs_median=float(sA["median"]),
                amp_min_q10_shotbs_std=float(sA["std"]),
                # debug
                boot_group_seed=int(sV["group_seed"]),
                boot_empty_frac=float(sV["boot_empty_frac"]),
                num_contexts_used_in_bootstrap=int(sV["num_contexts_used"]),
            )
        )
        boot_debug[f"run={run_label},n={n},i={i},j={j}"] = dbg

    df_boot = pd.DataFrame(boot_rows)
    df_sum = df_sum_trial.merge(df_boot, on=["run_label", "n", "i", "j", "pair"], how="left")

    # Point estimates used for plotting (Fig.5 alignment)
    if cfg.point_estimator == "trial":
        df_sum["V_circ_point"] = df_sum["V_circ"]
        df_sum["amp_min_q10_point"] = df_sum["amp_min_q10"]
    elif cfg.point_estimator == "boot_median":
        df_sum["V_circ_point"] = df_sum["V_circ_shotbs_median"]
        df_sum["amp_min_q10_point"] = df_sum["amp_min_q10_shotbs_median"]
    elif cfg.point_estimator == "boot_mean":
        df_sum["V_circ_point"] = df_sum["V_circ_shotbs_mean"]
        df_sum["amp_min_q10_point"] = df_sum["amp_min_q10_shotbs_mean"]
    else:
        raise ValueError(f"Unknown cfg.point_estimator={cfg.point_estimator!r}")

    # Run order for plotting (filter to those present)
    run_labels_present = set(df_sum["run_label"].unique())
    run_order = [r for r in cfg.run_order_plot if r in run_labels_present]

    return {
        "counts_df": df_counts_all,
        "context_df": df_ctx,
        "summary_df": df_sum,
        "run_order": run_order,
        "run_infos": infos_I + [info_B],
        "boot_debug": boot_debug,
        "cfg": cfg,
    }


def build_fig7_manifest(
    *,
    interleave_counts_json: Path,
    interleave_meta_json: Path,
    block_counts_json: Path,
    block_meta_json: Path,
    cfg: fig7AnalysisConfig,
    outputs: Dict[str, Any],
    style_rcparams: Optional[Dict[str, Any]] = None,
    extra_notes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Machine-readable manifest (mirrors Fig.5 conventions)."""

    notes = {
        "I_sum_definition": "I_sum pools I1–I4 into a shot-matched (2048 shots/circuit) estimate at the raw-count level; it is not an additional run.",
        "uncertainty": "Error bars are percentile (95%) shot-bootstrap CIs computed via per-circuit binomial resampling from raw counts.",
        "schedule_annotation": "Blocked segment is highlighted; boundaries mark interleaved→blocked→interleaved transitions.",
    }
    if extra_notes:
        notes.update(extra_notes)

    return {
        "figure": "S1",
        "inputs": {
            "interleave_counts_json": str(interleave_counts_json),
            "interleave_meta_json": str(interleave_meta_json),
            "block_counts_json": str(block_counts_json),
            "block_meta_json": str(block_meta_json),
            "sha256": {
                "interleave_counts_json": file_sha256(interleave_counts_json),
                "interleave_meta_json": file_sha256(interleave_meta_json),
                "block_counts_json": file_sha256(block_counts_json),
                "block_meta_json": file_sha256(block_meta_json),
            },
        },
        "config": asdict(cfg),
        "style_rcparams": style_rcparams or {},
        "notes": notes,
        "outputs": outputs,
    }
