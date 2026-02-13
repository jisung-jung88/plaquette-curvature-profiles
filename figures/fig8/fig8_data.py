# fig8_data.py
# Data processing for Appendix fig. 8 (run-to-run / day-to-day repeatability)
#
# Design goal (Blueprint v1.6):
#   - Compare two QPU datasets acquired at different times ("Day1" vs "Day2")
#   - Keep mapping/layout fixed by selecting (eta3, run) per day from a combined counts JSON
#   - Overlay Day1 vs Day2 for V_circ (or ΔV_circ) with shot-bootstrap CI95
#   - Report amp_min (mean + q10) alongside dispersion to separate reproducibility from visibility collapse
#
# This module is *pure data*: it outputs pandas DataFrames + a small manifest dict.
# Plotting/styling is implemented in fig8_plot.py.
#
# NOTE: This is a standalone version that does NOT depend on fig5_data.py.
#       All necessary functions from fig5_data have been inlined here.

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# Constants
# =============================================================================

REQUIRED_SETTINGS: Tuple[str, str, str, str] = ("cos_a", "sin_a", "cos_b", "sin_b")


# =============================================================================
# Configuration dataclass (originally from fig5_data.py)
# =============================================================================

@dataclass
class Fig5AnalysisConfig:
    """Analysis hyperparameters (must be recorded for reproducibility)."""
    boot_B: int = 5000
    seed: int = 12345
    ci_levels: Tuple[float, float] = (0.025, 0.975)
    amp_min_threshold: float = 0.0

    # How we choose the "point" estimate shown in Fig.5 Panel A.
    # - "trial": compute V_circ directly from the observed counts (raw point estimate)
    # - "boot_median": use the median of the shot-bootstrap distribution (default; ensures point ∈ percentile CI)
    # - "boot_mean": use the mean of the shot-bootstrap distribution
    point_estimator: str = "boot_median"

    # For future extensions; we keep them here for a stable manifest schema.
    drop_policy: str = "per_pair"            # ["per_pair", "intersection"]
    amp_threshold_mode: str = "fixed_from_csv"  # ["fixed_from_csv", "per_bootstrap"]


# =============================================================================
# Utility functions (originally from fig5_data.py)
# =============================================================================

def stable_int_seed(base_seed: int, key: str) -> int:
    """Deterministic per-group seed. Matches qpu_post_stats._stable_int_seed()."""
    h = hashlib.sha256(f"{base_seed}:{key}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % (2**32)


def file_sha256(path: Path, blocksize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(blocksize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _eta_key(eta3: float) -> float:
    """Canonical eta3 key used for matching CLI vs JSON values."""
    return round(float(eta3), 12)


def _normalize_run_value(run: Any) -> str:
    """Normalize run values (int/float/str) into a stable string for matching."""
    if run is None:
        return ""
    # numpy scalar ints
    try:
        if isinstance(run, (np.integer,)):
            return str(int(run))
    except Exception:
        pass

    if isinstance(run, bool):
        return str(run)
    if isinstance(run, int):
        return str(int(run))
    if isinstance(run, float) and run.is_integer():
        return str(int(run))
    return str(run)


def wrap_to_pi(x: np.ndarray) -> np.ndarray:
    return np.angle(np.exp(1j * np.asarray(x)))


def circular_mean_and_R(angles: np.ndarray) -> Tuple[float, float]:
    angles = np.asarray(angles, float)
    angles = angles[np.isfinite(angles)]
    if angles.size == 0:
        return float("nan"), float("nan")
    mu = np.mean(np.exp(1j * wrap_to_pi(angles)))
    return float(np.angle(mu)), float(np.abs(mu))


# =============================================================================
# Data loading (originally from fig5_data.py)
# =============================================================================

def load_combined_counts(path: Path) -> pd.DataFrame:
    """
    Parse the combined counts JSON into a long-form DataFrame with columns:
      eta3, run, n, i, j, z_rest_int, setting, shots, c0, c1, bit_order
    """
    obj = json.loads(path.read_text())

    # Support both:
    #  - combined format: list of {"eta3","run","data":[payload_n2..payload_n7]}
    #  - single payload format: {"schema": "...", ...}
    if isinstance(obj, list):
        blocks = obj
    else:
        blocks = [{"eta3": float(obj.get("eta3", 0.0)), "run": obj.get("run", ""), "data": [obj]}]

    rows: List[Dict[str, Any]] = []
    for block in blocks:
        eta3 = float(block.get("eta3", 0.0))
        run = block.get("run", None)
        data_list = block.get("data", [])
        if isinstance(data_list, dict):
            data_list = [data_list]

        for payload in data_list:
            schema = payload.get("schema")
            if schema is None:
                raise ValueError("Counts payload is missing 'schema' field.")
            n = int(payload.get("n"))
            bit_order = payload.get("bit_order", "lsb")
            shots_per_circuit = payload.get("shots_per_circuit", None)

            if schema == "counts.v1":
                pair = payload.get("pair")
                if not (isinstance(pair, list) and len(pair) == 2):
                    raise ValueError("counts.v1 payload missing 'pair'=[i,j].")
                i, j = map(int, pair)

                for r in payload.get("data", []):
                    z = int(r["z_rest_int"])
                    setting = str(r["setting"])
                    c0 = int(r["counts"].get("0", 0))
                    c1 = int(r["counts"].get("1", 0))
                    shots = r.get("shots", shots_per_circuit)
                    if shots is None:
                        shots = c0 + c1
                    shots = int(shots)

                    rows.append(
                        dict(
                            eta3=eta3,
                            run=run,
                            n=n,
                            i=i,
                            j=j,
                            z_rest_int=z,
                            setting=setting,
                            shots=shots,
                            c0=c0,
                            c1=c1,
                            bit_order=bit_order,
                        )
                    )

            elif schema == "counts.v2":
                for r in payload.get("data", []):
                    pair = r.get("pair")
                    if not (isinstance(pair, list) and len(pair) == 2):
                        raise ValueError("counts.v2 record missing 'pair'=[i,j].")
                    i, j = map(int, pair)

                    z = int(r["z_rest_int"])
                    setting = str(r["setting"])
                    c0 = int(r["counts"].get("0", 0))
                    c1 = int(r["counts"].get("1", 0))
                    shots = r.get("shots", shots_per_circuit)
                    if shots is None:
                        shots = c0 + c1
                    shots = int(shots)

                    rows.append(
                        dict(
                            eta3=eta3,
                            run=run,
                            n=n,
                            i=i,
                            j=j,
                            z_rest_int=z,
                            setting=setting,
                            shots=shots,
                            c0=c0,
                            c1=c1,
                            bit_order=bit_order,
                        )
                    )
            else:
                raise ValueError(f"Unsupported counts schema: {schema}")

    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"No counts records parsed from: {path}")

    # dtypes
    df["eta3"] = df["eta3"].astype(float)
    for c in ["n", "i", "j", "z_rest_int", "shots", "c0", "c1"]:
        df[c] = df[c].astype(int)
    df["setting"] = df["setting"].astype(str)
    df["bit_order"] = df["bit_order"].astype(str)
    return df


# =============================================================================
# eta->run selection (originally from fig5_data.py)
# =============================================================================

def apply_eta_run_selection_to_counts(
    counts_df: pd.DataFrame,
    eta_run_selection: Dict[float, Any],
    *,
    counts_json: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Filter a counts_df to keep only the selected run for each eta3 in eta_run_selection.

    Requirements:
      - If a requested (eta3, run) does not exist in counts_json, raise immediately.
      - If eta3 is not in eta_run_selection, we keep all its runs (backward compatible).
    """
    if not eta_run_selection:
        return counts_df

    df = counts_df.copy()
    df["_eta_key"] = df["eta3"].map(_eta_key)
    df["_run_norm"] = df["run"].map(_normalize_run_value)

    avail = set(zip(df["_eta_key"].tolist(), df["_run_norm"].tolist()))

    # Validate requested pairs exist.
    for eta_k, run_req in eta_run_selection.items():
        ek = _eta_key(eta_k)
        rn = _normalize_run_value(run_req)
        if (ek, rn) not in avail:
            runs_for_eta = sorted({r for (e, r) in avail if e == ek})
            src = str(counts_json) if counts_json is not None else "<counts_json>"
            raise ValueError(
                f"Requested (eta3={float(eta_k)}, run={run_req!r}) via --eta-run was not found in counts file {src}. "
                f"Available runs for eta3={float(eta_k)}: {runs_for_eta}"
            )

    # Keep only the requested run for each specified eta3.
    keep = np.ones(len(df), dtype=bool)
    for eta_k, run_req in eta_run_selection.items():
        ek = _eta_key(eta_k)
        rn = _normalize_run_value(run_req)
        keep &= ((df["_eta_key"] != ek) | (df["_run_norm"] == rn))

    df = df.loc[keep].drop(columns=["_eta_key", "_run_norm"])
    if df.empty:
        raise ValueError("All counts records were filtered out by eta_run_selection; nothing left to analyze.")
    return df


# =============================================================================
# Context table building (originally from fig5_data.py)
# =============================================================================

def build_context_table(counts_df: pd.DataFrame) -> pd.DataFrame:
    """
    Context-level point estimates from raw counts:
      - expectations m for each setting
      - kappa_hat (phasor estimator)
      - amp_min per context
    """
    df = counts_df.copy()
    df["m"] = (df["c0"] - df["c1"]) / df["shots"].astype(float)

    wide = (
        df.pivot_table(
            index=["eta3", "n", "i", "j", "z_rest_int"],
            columns="setting",
            values="m",
            aggfunc="first",
        )
        .reset_index()
    )

    for s in REQUIRED_SETTINGS:
        if s not in wide.columns:
            wide[s] = np.nan

    wide["has_all_settings"] = wide[list(REQUIRED_SETTINGS)].notna().all(axis=1)

    ua = wide["cos_a"].to_numpy(float) + 1j * wide["sin_a"].to_numpy(float)
    ub = wide["cos_b"].to_numpy(float) + 1j * wide["sin_b"].to_numpy(float)

    wide["kappa_hat"] = np.angle(ua * np.conj(ub))
    wide["amp_a"] = np.abs(ua)
    wide["amp_b"] = np.abs(ub)
    wide["amp_min_ctx"] = np.minimum(wide["amp_a"], wide["amp_b"])
    return wide


# =============================================================================
# Group-level metrics (originally from fig5_data.py)
# =============================================================================

def compute_group_point_metrics(context_df: pd.DataFrame, amp_min_threshold: float = 0.0) -> pd.DataFrame:
    """
    One row per (eta3,n,i,j).
    Matches the columns used by seed0316_eta_sweep_summary.csv (plus context counts).
    """
    rows: List[Dict[str, Any]] = []
    for (eta3, n, i, j), g in context_df.groupby(["eta3", "n", "i", "j"]):
        mask = g["has_all_settings"].to_numpy(bool) & np.isfinite(g["kappa_hat"].to_numpy(float))
        if amp_min_threshold > 0.0:
            mask = mask & (g["amp_min_ctx"].to_numpy(float) >= amp_min_threshold)

        kappa = g.loc[mask, "kappa_hat"].to_numpy(float)

        mean_angle, R = circular_mean_and_R(kappa)
        V = float("nan") if not math.isfinite(R) else float(np.clip(1.0 - R, 0.0, 1.0))

        amp_min = g.loc[mask, "amp_min_ctx"].to_numpy(float)
        amp_min = amp_min[np.isfinite(amp_min)]
        amp_mean = float(np.mean(amp_min)) if amp_min.size else float("nan")
        amp_q10 = float(np.quantile(amp_min, 0.10)) if amp_min.size else float("nan")

        q90_abs = float(np.quantile(np.abs(wrap_to_pi(kappa)), 0.90)) if kappa.size else float("nan")

        rows.append(
            dict(
                eta3=float(eta3),
                n=int(n),
                i=int(i),
                j=int(j),
                pair=f"({int(i)},{int(j)})",
                kappa_ctx_circ_var_trial=V,
                amp_min_mean_ctx_trial=amp_mean,
                amp_min_q10_ctx_trial=amp_q10,
                kappa_ctx_circ_mean_trial=mean_angle,
                kappa_abs_q90_ctx_trial=q90_abs,
                num_contexts_total=int(len(g)),
                num_contexts_used=int(mask.sum()),
            )
        )
    return pd.DataFrame(rows)


# =============================================================================
# Bootstrap (originally from fig5_data.py)
# =============================================================================

def bootstrap_circ_var(
    counts_df_group: pd.DataFrame,
    cfg: Fig5AnalysisConfig,
    trial_id: int = 0
) -> Tuple[np.ndarray, Dict[str, float], Dict[str, Any]]:
    """
    Shot bootstrap for V_circ for a single group (eta3,n,i,j).
    We intentionally match qpu_post_stats' bootstrap semantics:
      - draw c0' ~ Binomial(shots, p0=c0/shots)
      - compute m = (2*c0' - shots)/shots
      - build A,Bc, then kappa = angle(A * conj(Bc))
      - circ_var = 1 - |mean(exp(i kappa))|
    """
    contexts = sorted(counts_df_group["z_rest_int"].unique())
    C = len(contexts)
    ctx_idx = {z: k for k, z in enumerate(contexts)}
    s_idx = {s: k for k, s in enumerate(REQUIRED_SETTINGS)}

    shots = np.zeros((C, 4), dtype=int)
    c0 = np.zeros((C, 4), dtype=int)

    for r in counts_df_group.itertuples(index=False):
        ci = ctx_idx[int(r.z_rest_int)]
        si = s_idx[str(r.setting)]
        shots[ci, si] = int(r.shots)
        c0[ci, si] = int(r.c0)

    has_all = np.all(shots > 0, axis=1)

    # Base mask uses the point estimate (fixed mode)
    m_point = (2 * c0 - shots) / shots
    ua_point = m_point[:, 0] + 1j * m_point[:, 1]
    ub_point = m_point[:, 2] + 1j * m_point[:, 3]
    kappa_point = np.angle(ua_point * np.conj(ub_point))
    amp_min_point = np.minimum(np.abs(ua_point), np.abs(ub_point))

    base_mask = has_all & np.isfinite(kappa_point)
    if cfg.amp_min_threshold > 0.0 and cfg.amp_threshold_mode == "fixed_from_csv":
        base_mask = base_mask & (amp_min_point >= cfg.amp_min_threshold)

    n = int(counts_df_group["n"].iloc[0])
    i = int(counts_df_group["i"].iloc[0])
    j = int(counts_df_group["j"].iloc[0])

    group_seed = stable_int_seed(cfg.seed, f"n={n},i={i},j={j},trial={trial_id}")
    rng = np.random.default_rng(group_seed)

    p0 = np.divide(c0, shots, out=np.zeros_like(c0, dtype=float), where=shots > 0)
    c0_bs = rng.binomial(n=shots, p=p0, size=(cfg.boot_B,) + shots.shape)  # (B,C,4)

    m = (2.0 * c0_bs - shots) / shots

    A = m[:, :, s_idx["cos_a"]] + 1j * m[:, :, s_idx["sin_a"]]
    Bc = m[:, :, s_idx["cos_b"]] + 1j * m[:, :, s_idx["sin_b"]]
    kappa = np.angle(A * np.conj(Bc))  # (B,C)

    if cfg.amp_min_threshold > 0.0 and cfg.amp_threshold_mode == "per_bootstrap":
        amp_a = np.sqrt(m[:, :, s_idx["cos_a"]] ** 2 + m[:, :, s_idx["sin_a"]] ** 2)
        amp_b = np.sqrt(m[:, :, s_idx["cos_b"]] ** 2 + m[:, :, s_idx["sin_b"]] ** 2)
        amp_min = np.minimum(amp_a, amp_b)
        mask = (amp_min >= cfg.amp_min_threshold) & has_all[None, :]
    else:
        mask = np.broadcast_to(base_mask, (cfg.boot_B, C))

    ph = np.exp(1j * kappa)
    sum_ph = (ph * mask).sum(axis=1)
    cnt = mask.sum(axis=1)
    mean_ph = np.where(cnt > 0, sum_ph / cnt, np.nan + 1j * np.nan)
    V = 1.0 - np.abs(mean_ph)
    # Numerical safety: |mean_ph| can exceed 1 by ~1e-16 due to roundoff.
    V = np.clip(V, 0.0, 1.0)
    V[cnt == 0] = np.nan

    lo, hi = cfg.ci_levels
    summary = dict(
        mean=float(np.nanmean(V)),
        median=float(np.nanmedian(V)),
        std=float(np.nanstd(V, ddof=1)),
        ci_lo=float(np.nanquantile(V, lo)),
        ci_hi=float(np.nanquantile(V, hi)),
        boot_empty_frac=float(np.mean(cnt == 0)),
        num_contexts_used_in_bootstrap=int(np.sum(base_mask)),
        group_seed=int(group_seed),
    )
    debug = dict(contexts=contexts, base_mask=base_mask.tolist())
    return V, summary, debug


# =============================================================================
# Fig.9 specific functions (original fig8_data.py code)
# =============================================================================

def select_counts_for_day(
    *,
    counts_df_all: pd.DataFrame,
    eta_run_selection: Dict[float, Any],
    counts_json: Optional[Path] = None,
    keep_only_selected_etas: bool = True,
) -> pd.DataFrame:
    """Select a day-specific slice of the combined counts table.

    We first reuse the eta->run filter (which validates requested (eta,run)
    exist), then optionally drop any eta values not explicitly requested.
    """
    if not eta_run_selection:
        raise ValueError("eta_run_selection is empty. Provide at least one --day*-eta-run mapping.")

    df = apply_eta_run_selection_to_counts(
        counts_df_all,
        eta_run_selection,
        counts_json=counts_json,
    ).copy()

    if keep_only_selected_etas:
        want = {_eta_key(float(e)) for e in eta_run_selection.keys()}
        df["_eta_key"] = df["eta3"].map(_eta_key)
        df = df[df["_eta_key"].isin(want)].drop(columns=["_eta_key"])
        if df.empty:
            raise ValueError("All records were filtered out after keep_only_selected_etas=True.")
    return df


def _compute_summary_and_context(
    *,
    counts_df: pd.DataFrame,
    cfg: Fig5AnalysisConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compute context_df and per-(eta,n,pair) summary with shot-bootstrap CI."""
    context_df = build_context_table(counts_df)

    point_df = compute_group_point_metrics(context_df, amp_min_threshold=cfg.amp_min_threshold)

    boot_rows: List[Dict[str, Any]] = []
    for (eta3, n, i, j), g in counts_df.groupby(["eta3", "n", "i", "j"], sort=True):
        _, summ, _dbg = bootstrap_circ_var(g, cfg, trial_id=0)
        boot_rows.append(
            dict(
                eta3=float(eta3),
                n=int(n),
                i=int(i),
                j=int(j),
                kappa_ctx_circ_var_shotbs_ci95_lo=float(summ["ci_lo"]),
                kappa_ctx_circ_var_shotbs_ci95_hi=float(summ["ci_hi"]),
                kappa_ctx_circ_var_shotbs_mean=float(summ["mean"]),
                kappa_ctx_circ_var_shotbs_median=float(summ["median"]),
                kappa_ctx_circ_var_shotbs_std=float(summ["std"]),
                boot_empty_frac=float(summ["boot_empty_frac"]),
                boot_group_seed=int(summ["group_seed"]),
            )
        )

    boot_df = pd.DataFrame(boot_rows)
    summary_df = point_df.merge(boot_df, on=["eta3", "n", "i", "j"], how="left")

    # Point estimate used for plotting
    if cfg.point_estimator == "trial":
        summary_df["kappa_ctx_circ_var_point"] = summary_df["kappa_ctx_circ_var_trial"]
    elif cfg.point_estimator == "boot_median":
        summary_df["kappa_ctx_circ_var_point"] = summary_df["kappa_ctx_circ_var_shotbs_median"]
    elif cfg.point_estimator == "boot_mean":
        summary_df["kappa_ctx_circ_var_point"] = summary_df["kappa_ctx_circ_var_shotbs_mean"]
    else:
        raise ValueError(
            f"Unsupported cfg.point_estimator={cfg.point_estimator!r}. "
            "Expected one of: 'trial', 'boot_median', 'boot_mean'."
        )

    # Safety
    summary_df["kappa_ctx_circ_var_point"] = summary_df["kappa_ctx_circ_var_point"].astype(float).clip(0.0, 1.0)

    # Canonical ordering (subset of Fig.5 summary columns)
    ordered_cols = [
        "eta3",
        "n",
        "pair",
        "kappa_ctx_circ_var_point",
        "kappa_ctx_circ_var_trial",
        "kappa_ctx_circ_var_shotbs_ci95_lo",
        "kappa_ctx_circ_var_shotbs_ci95_hi",
        "kappa_ctx_circ_var_shotbs_median",
        "kappa_ctx_circ_var_shotbs_mean",
        "amp_min_mean_ctx_trial",
        "amp_min_q10_ctx_trial",
        "num_contexts_total",
        "num_contexts_used",
        "kappa_ctx_circ_var_shotbs_std",
        "boot_empty_frac",
        "boot_group_seed",
    ]
    # Some columns exist only because compute_group_point_metrics creates them.
    ordered_cols = [c for c in ordered_cols if c in summary_df.columns]
    summary_df = summary_df[ordered_cols].sort_values(["eta3", "n", "pair"]).reset_index(drop=True)
    return summary_df, context_df


def _compute_deltaV(
    *,
    counts_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    cfg: Fig5AnalysisConfig,
    signal_pair: Tuple[int, int],
    control_pair: Tuple[int, int],
) -> pd.DataFrame:
    """Compute ΔV_circ = V(signal) - V(control) with shot-bootstrap CI.

    Uses the same deterministic pairing trick as Fig.5:
      - bootstrap each pair with the same per-pair seed
      - subtract replicate-wise
    """
    lo, hi = cfg.ci_levels
    delta_rows: List[Dict[str, Any]] = []

    for eta3 in sorted(summary_df["eta3"].unique()):
        for n in sorted(summary_df["n"].unique()):
            if int(n) < 5:
                continue

            sig = counts_df[
                (counts_df["eta3"] == float(eta3))
                & (counts_df["n"] == int(n))
                & (counts_df["i"] == int(signal_pair[0]))
                & (counts_df["j"] == int(signal_pair[1]))
            ]
            ctl = counts_df[
                (counts_df["eta3"] == float(eta3))
                & (counts_df["n"] == int(n))
                & (counts_df["i"] == int(control_pair[0]))
                & (counts_df["j"] == int(control_pair[1]))
            ]
            if sig.empty or ctl.empty:
                continue

            V_sig, *_ = bootstrap_circ_var(sig, cfg, trial_id=0)
            V_ctl, *_ = bootstrap_circ_var(ctl, cfg, trial_id=0)
            dV = V_sig - V_ctl

            # point estimate (uses same point estimator already baked into summary_df)
            sig_pt = summary_df[
                (summary_df["eta3"] == float(eta3))
                & (summary_df["n"] == int(n))
                & (summary_df["pair"] == f"({signal_pair[0]},{signal_pair[1]})")
            ]["kappa_ctx_circ_var_point"].values
            ctl_pt = summary_df[
                (summary_df["eta3"] == float(eta3))
                & (summary_df["n"] == int(n))
                & (summary_df["pair"] == f"({control_pair[0]},{control_pair[1]})")
            ]["kappa_ctx_circ_var_point"].values
            dV_point = float(sig_pt[0] - ctl_pt[0]) if len(sig_pt) and len(ctl_pt) else float("nan")

            delta_rows.append(
                dict(
                    eta3=float(eta3),
                    n=int(n),
                    delta_V_circ=float(dV_point),
                    delta_shotbs_ci_lo=float(np.nanquantile(dV, lo)),
                    delta_shotbs_ci_hi=float(np.nanquantile(dV, hi)),
                )
            )

    return pd.DataFrame(delta_rows).sort_values(["eta3", "n"]).reset_index(drop=True)


def compute_fig8_day_products(
    *,
    counts_json: Path,
    cfg: Fig5AnalysisConfig,
    eta_run_selection: Dict[float, Any],
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
    keep_only_selected_etas: bool = True,
) -> Dict[str, Any]:
    """Compute all data products for one "day" selection."""
    counts_df_all = load_combined_counts(counts_json)
    counts_df = select_counts_for_day(
        counts_df_all=counts_df_all,
        eta_run_selection=eta_run_selection,
        counts_json=counts_json,
        keep_only_selected_etas=keep_only_selected_etas,
    )

    summary_df, context_df = _compute_summary_and_context(counts_df=counts_df, cfg=cfg)
    delta_df = _compute_deltaV(
        counts_df=counts_df,
        summary_df=summary_df,
        cfg=cfg,
        signal_pair=signal_pair,
        control_pair=control_pair,
    )

    return dict(
        counts_df=counts_df,
        context_df=context_df,
        summary_df=summary_df,
        delta_df=delta_df,
    )


def build_fig8_manifest(
    *,
    counts_json: Path,
    cfg: Fig5AnalysisConfig,
    day1_selection: Dict[float, Any],
    day2_selection: Dict[float, Any],
    n_key: int,
    metric_mode: str,
    signal_pair: Tuple[int, int],
    control_pair: Tuple[int, int],
    outputs: Dict[str, str | None],
    style_rcparams: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Small machine-readable manifest (mirrors Fig.5 conventions)."""
    return dict(
        figure="Fig.9",
        description="Run-to-run / day-to-day repeatability at fixed layout",
        inputs=dict(
            counts_json=str(counts_json),
            counts_sha256=file_sha256(counts_json),
        ),
        analysis_config=asdict(cfg),
        selection=dict(
            day1={str(_eta_key(k)): v for k, v in day1_selection.items()},
            day2={str(_eta_key(k)): v for k, v in day2_selection.items()},
        ),
        design=dict(
            n_key=int(n_key),
            metric_mode=str(metric_mode),
            signal_pair=list(map(int, signal_pair)),
            control_pair=list(map(int, control_pair)),
        ),
        style_rcparams=style_rcparams,
        outputs=outputs,
    )
