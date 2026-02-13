"""fig5_data.py

Fig.5 (UPDATED): Panels **A,B only**.

This is the AB-only version of the original Fig.5 generator. The previous
representative κ-profile panel (old Panel C) has been moved out to a
standalone figure (new Fig.6 in the updated blueprint).

Build Fig.5 data products directly from TWO inputs:
  (1) combined counts JSON
  (2) combined run_meta JSON

Outputs are pure-python objects / pandas DataFrames. Plotting is handled
separately in ``fig5_plot.py``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

REQUIRED_SETTINGS: Tuple[str, str, str, str] = ("cos_a", "sin_a", "cos_b", "sin_b")


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


def load_combined_run_meta(path: Path) -> List[Dict[str, Any]]:
    """
    Return the combined run_meta JSON (list of eta blocks).
    We don't enforce a schema beyond expecting:
      [{"eta3":..., "run":..., "data":[... per-n meta dicts ...]}, ...]
    """
    obj = json.loads(path.read_text())
    if isinstance(obj, list):
        return obj
    return [{"eta3": float(obj.get("eta3", 0.0)), "run": obj.get("run", ""), "data": [obj]}]


# -----------------------------------------------------------------------------
# Optional eta3->run selection (CLI-controlled)
# -----------------------------------------------------------------------------

def _eta_key(eta3: float) -> float:
    """Canonical eta3 key used for matching CLI vs JSON values."""
    return round(float(eta3), 12)


def _normalize_run_value(run: Any) -> str:
    """Normalize run values (int/float/str) into a stable string for matching."""
    if run is None:
        return ""
    # numpy scalar ints
    try:
        import numpy as _np  # local import to avoid polluting module namespace

        if isinstance(run, (_np.integer,)):
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


def apply_eta_run_selection_to_run_meta(
    run_meta_blocks: List[Dict[str, Any]],
    eta_run_selection: Dict[float, Any],
    *,
    run_meta_json: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Filter run_meta blocks consistently with eta_run_selection (best-effort)."""
    if not eta_run_selection:
        return run_meta_blocks

    # If run isn't present in the meta blocks, we cannot filter deterministically.
    if not any("run" in blk for blk in run_meta_blocks):
        return run_meta_blocks

    # Canonicalize selection so float rounding can't break dict lookups.
    sel_norm: Dict[float, str] = {
        _eta_key(float(k)): _normalize_run_value(v) for k, v in eta_run_selection.items()
    }
    sel_keys = set(sel_norm.keys())

    avail = {
        (_eta_key(float(blk.get("eta3", 0.0))), _normalize_run_value(blk.get("run", "")))
        for blk in run_meta_blocks
    }

    for ek, rn in sel_norm.items():
        if (ek, rn) not in avail:
            runs_for_eta = sorted({r for (e, r) in avail if e == ek})
            src = str(run_meta_json) if run_meta_json is not None else "<run_meta_json>"
            raise ValueError(
                f"Requested (eta3={float(ek)}, run={eta_run_selection.get(ek, rn)!r}) via --eta-run was not found in run_meta file {src}. "
                f"Available runs for eta3={float(ek)}: {runs_for_eta}"
            )

    out: List[Dict[str, Any]] = []
    for blk in run_meta_blocks:
        ek = _eta_key(float(blk.get("eta3", 0.0)))
        rn = _normalize_run_value(blk.get("run", ""))
        if ek in sel_keys:
            if rn == sel_norm[ek]:
                out.append(blk)
        else:
            out.append(blk)

    return out


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


def wrap_to_pi(x: np.ndarray) -> np.ndarray:
    return np.angle(np.exp(1j * np.asarray(x)))


def circular_mean_and_R(angles: np.ndarray) -> Tuple[float, float]:
    angles = np.asarray(angles, float)
    angles = angles[np.isfinite(angles)]
    if angles.size == 0:
        return float("nan"), float("nan")
    mu = np.mean(np.exp(1j * wrap_to_pi(angles)))
    return float(np.angle(mu)), float(np.abs(mu))


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


def bootstrap_circ_var(counts_df_group: pd.DataFrame, cfg: Fig5AnalysisConfig, trial_id: int = 0) -> Tuple[np.ndarray, Dict[str, float], Dict[str, Any]]:
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


def compute_fig5_products(
    counts_json: Path,
    run_meta_json: Path,
    cfg: Fig5AnalysisConfig,
    eta_run_selection: Optional[Dict[float, Any]] = None,
    # (deprecated) Previously used for the old Panel C profile extract.
    # Kept only for backward compatibility with old CLI calls.
    profile_eta3: float = 0.2,
    profile_n: int = 7,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
) -> Dict[str, Any]:
    """
    Main entry point for the "values generation" stage.

    Returns:
      {
        "counts_df": long counts df,
        "context_df": context-level point df,
        "summary_df": per-(eta3,n,pair) summary with CI columns,
        "delta_df": optional ΔV table for n>=5 (computed, not necessarily plotted),
        "meta_map": (eta3,n)->run_meta entry,
        "debug": per-group bootstrap debug
      }
    """
    counts_df = load_combined_counts(counts_json)
    run_meta_blocks = load_combined_run_meta(run_meta_json)

    if eta_run_selection:
        counts_df = apply_eta_run_selection_to_counts(counts_df, eta_run_selection, counts_json=counts_json)
        run_meta_blocks = apply_eta_run_selection_to_run_meta(run_meta_blocks, eta_run_selection, run_meta_json=run_meta_json)

    # Map (eta3,n)->meta entry (best-effort)
    meta_map: Dict[Tuple[float, int], Dict[str, Any]] = {}
    for blk in run_meta_blocks:
        eta3 = float(blk.get("eta3", 0.0))
        for entry in blk.get("data", []):
            n = int(entry.get("model", {}).get("n", entry.get("n", 0)))
            meta_map[(eta3, n)] = entry

    context_df = build_context_table(counts_df)

    # Point metrics
    point_df = compute_group_point_metrics(context_df, amp_min_threshold=cfg.amp_min_threshold)

    # Bootstrap CIs
    boot_rows: List[Dict[str, Any]] = []
    boot_debug: Dict[str, Any] = {}

    for (eta3, n, i, j), g in counts_df.groupby(["eta3", "n", "i", "j"]):
        V_boot, summ, dbg = bootstrap_circ_var(g, cfg, trial_id=0)
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
        boot_debug[f"eta3={eta3},n={n},i={i},j={j}"] = dbg

    boot_df = pd.DataFrame(boot_rows)

    summary_df = point_df.merge(boot_df, on=["eta3", "n", "i", "j"], how="left")

    # Point estimate used for plotting/reporting in Fig.5 Panel A.
    # Default ("boot_median") avoids the confusing (but not mathematically impossible)
    # situation where a percentile CI does not include a raw point estimate for a biased statistic.
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

    # Numerical safety (should already be in-range, but keep it explicit).
    summary_df["kappa_ctx_circ_var_point"] = summary_df["kappa_ctx_circ_var_point"].astype(float).clip(lower=0.0, upper=1.0)


    # Keep the canonical summary columns first (like seed0316_eta_sweep_summary.csv)
    ordered_cols = [
        "eta3",
        "n",
        "pair",
        # V_circ point estimate shown in Panel A (see cfg.point_estimator)
        "kappa_ctx_circ_var_point",
        # Raw point estimate from the observed counts (kept for audit/debug)
        "kappa_ctx_circ_var_trial",
        # Shot-bootstrap percentile CI (computed from V_boot after clipping to [0,1])
        "kappa_ctx_circ_var_shotbs_ci95_lo",
        "kappa_ctx_circ_var_shotbs_ci95_hi",
        # Shot-bootstrap location summaries (useful for diagnosing bias)
        "kappa_ctx_circ_var_shotbs_median",
        "kappa_ctx_circ_var_shotbs_mean",
        # Quality diagnostics
        "amp_min_mean_ctx_trial",
        "amp_min_q10_ctx_trial",
        "kappa_ctx_circ_mean_trial",
        "kappa_abs_q90_ctx_trial",
        # extra diagnostics
        "num_contexts_total",
        "num_contexts_used",
        "kappa_ctx_circ_var_shotbs_std",
        "boot_empty_frac",
        "boot_group_seed",
    ]
    summary_df = summary_df[ordered_cols].sort_values(["eta3", "n", "pair"]).reset_index(drop=True)

    # ΔV_circ table (useful for QPU defense; not mandatory to plot in Fig.5 panel design)
    delta_rows: List[Dict[str, Any]] = []
    lo, hi = cfg.ci_levels

    for eta3 in sorted(summary_df["eta3"].unique()):
        for n in sorted(summary_df["n"].unique()):
            if n < 5:
                continue

            sig = counts_df[
                (counts_df["eta3"] == eta3)
                & (counts_df["n"] == n)
                & (counts_df["i"] == signal_pair[0])
                & (counts_df["j"] == signal_pair[1])
            ]
            ctl = counts_df[
                (counts_df["eta3"] == eta3)
                & (counts_df["n"] == n)
                & (counts_df["i"] == control_pair[0])
                & (counts_df["j"] == control_pair[1])
            ]
            if sig.empty or ctl.empty:
                continue

            # Deterministic: use the same per-pair seeds as in the single-pair bootstrap,
            # then pair by replicate index (b) to form ΔV_b = V_sig_b - V_ctl_b.
            V_sig, *_ = bootstrap_circ_var(sig, cfg, trial_id=0)
            V_ctl, *_ = bootstrap_circ_var(ctl, cfg, trial_id=0)
            dV = V_sig - V_ctl

            # point estimate delta
            V_sig_point = summary_df[(summary_df["eta3"] == eta3) & (summary_df["n"] == n) & (summary_df["pair"] == f"({signal_pair[0]},{signal_pair[1]})")]["kappa_ctx_circ_var_point"].values
            V_ctl_point = summary_df[(summary_df["eta3"] == eta3) & (summary_df["n"] == n) & (summary_df["pair"] == f"({control_pair[0]},{control_pair[1]})")]["kappa_ctx_circ_var_point"].values
            if len(V_sig_point) and len(V_ctl_point):
                dV_point = float(V_sig_point[0] - V_ctl_point[0])
            else:
                dV_point = float("nan")

            delta_rows.append(
                dict(
                    eta3=float(eta3),
                    n=int(n),
                    delta_V_circ=dV_point,
                    delta_shotbs_ci_lo=float(np.nanquantile(dV, lo)),
                    delta_shotbs_ci_hi=float(np.nanquantile(dV, hi)),
                )
            )

    delta_df = pd.DataFrame(delta_rows).sort_values(["eta3", "n"]).reset_index(drop=True)

    # NOTE: The old Fig.5 Panel C (representative κ-profile plot) has been
    # moved into the new standalone figure (updated blueprint: Fig.6).

    return dict(
        counts_df=counts_df,
        context_df=context_df,
        summary_df=summary_df,
        delta_df=delta_df,
        meta_map=meta_map,
        boot_debug=boot_debug,
    )


def build_fig5_manifest(
    *,
    counts_json: Path,
    run_meta_json: Path,
    cfg: Fig5AnalysisConfig,
    summary_df: pd.DataFrame,
    outputs: Dict[str, str],
    eta_run_selection: Optional[Dict[float, Any]] = None,
    style_rcparams: Optional[Dict[str, Any]] = None,
    fig_size_inches: Tuple[float, float] = (10.0, 3.6),
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
    # Optional style metadata: keep the manifest aligned with the plotted palette.
    sweep_palette: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Machine-readable "figure spec" for paper-writing assistants.

    This manifest corresponds to the UPDATED Fig.5 (Panels A,B only).

    Notes on style fields:
      - `sweep_palette` controls the η₃ sweep colors used in Panels A/B.

    If these are not provided, we fall back to Matplotlib tab colors (backward compatible),
    but downstream tools that depend on perceptual consistency across figures should pass
    the exact palette used by the plotting code.
    """
    eta_vals = [float(x) for x in sorted(summary_df["eta3"].unique())]
    ns = [int(x) for x in sorted(summary_df["n"].unique())]

    if sweep_palette is None or len(sweep_palette) == 0:
        palette = ["tab:blue", "tab:orange", "tab:green", "tab:purple", "tab:brown"]
        palette_source = "matplotlib_tab"
    else:
        palette = list(sweep_palette)
        palette_source = "caller_provided"

    color_map = {float(eta): palette[k % len(palette)] for k, eta in enumerate(eta_vals)}

    pair_styles = {
        f"({signal_pair[0]},{signal_pair[1]})": dict(marker="o", linestyle="-", markerfacecolor=None, label="Signal"),
        f"({control_pair[0]},{control_pair[1]})": dict(marker="s", linestyle="--", markerfacecolor="white", label="Control"),
    }

    def _panelA_traces() -> List[Dict[str, Any]]:
        traces: List[Dict[str, Any]] = []
        for eta in eta_vals:
            for pair, sty in pair_styles.items():
                df = summary_df[(summary_df["eta3"] == eta) & (summary_df["pair"] == pair)].sort_values("n")
                if df.empty:
                    continue
                traces.append(
                    dict(
                        eta3=float(eta),
                        pair=pair,
                        x_n=df["n"].astype(int).tolist(),
                        # Point estimate used for the plotted marker/line.
                        y_V_circ=df["kappa_ctx_circ_var_point"].astype(float).tolist(),
                        # Raw trial value (kept for debugging).
                        y_V_circ_trial=df["kappa_ctx_circ_var_trial"].astype(float).tolist(),
                        ci95_lo=df["kappa_ctx_circ_var_shotbs_ci95_lo"].astype(float).tolist(),
                        ci95_hi=df["kappa_ctx_circ_var_shotbs_ci95_hi"].astype(float).tolist(),
                        style=dict(
                            color=color_map[float(eta)],
                            marker=sty["marker"],
                            linestyle=sty["linestyle"],
                            markerfacecolor=sty["markerfacecolor"],
                        ),
                    )
                )
        return traces

    def _panelB_traces() -> List[Dict[str, Any]]:
        traces: List[Dict[str, Any]] = []
        for eta in eta_vals:
            for pair, sty in pair_styles.items():
                df = summary_df[(summary_df["eta3"] == eta) & (summary_df["pair"] == pair)].sort_values("n")
                if df.empty:
                    continue
                traces.append(
                    dict(
                        eta3=float(eta),
                        pair=pair,
                        x_n=df["n"].astype(int).tolist(),
                        y_amp_min_mean=df["amp_min_mean_ctx_trial"].astype(float).tolist(),
                        y_amp_min_q10=df["amp_min_q10_ctx_trial"].astype(float).tolist(),
                        style=dict(
                            color=color_map[float(eta)],
                            marker=sty["marker"],
                            linestyle=sty["linestyle"],
                            markerfacecolor=sty["markerfacecolor"],
                        ),
                    )
                )
        return traces

    inputs_dict = dict(
        counts_json=dict(path=str(counts_json), sha256=file_sha256(counts_json)),
        run_meta_json=dict(path=str(run_meta_json), sha256=file_sha256(run_meta_json)),
    )
    if eta_run_selection:
        inputs_dict["eta_run_selection"] = [
            dict(eta3=float(k), run=eta_run_selection[k]) for k in sorted(eta_run_selection.keys())
        ]

    # JSON-friendly color map (keys must be strings)
    eta3_color_map_json = {f"{float(e)}": color_map[float(e)] for e in eta_vals}

    return dict(
        figure_id="Fig5",
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        inputs=inputs_dict,
        analysis_config=asdict(cfg),
        layout=dict(
            figure_size_inches=list(fig_size_inches),
            panels=dict(
                A=dict(grid_cell=[0, 0], title="V_circ vs n (η3 sweep; signal+control)"),
                B=dict(grid_cell=[0, 1], title="amp_min vs n (η3 sweep; signal+control)"),
            ),
            style=dict(
                rcParams=(
                    style_rcparams
                    if style_rcparams is not None
                    else dict(
                        figure_dpi=300,
                        font_family="serif",
                        font_serif=["Times New Roman", "DejaVu Serif"],
                        mathtext_fontset="cm",
                        axes_labelsize=12,
                        xtick_labelsize=10,
                        ytick_labelsize=10,
                        legend_fontsize=10,
                        axes_grid=True,
                        grid_alpha=0.5,
                        grid_linestyle="--",
                    )
                ),
                palette=dict(
                    eta3_color_map=eta3_color_map_json,
                    eta3_palette_source=palette_source,
                ),
            ),
        ),
        data=dict(
            n_values=ns,
            eta3_values=eta_vals,
            eta3_color_map=eta3_color_map_json,
            panel_A_traces=_panelA_traces(),
            panel_B_traces=_panelB_traces(),
            notes=dict(
                connected_control_starts_at_n=5,
                caption_must_include=[
                    "Connected-control data starts at n=5 due to hardware coupling constraints; simulation provides the complete n-sweep evidence.",
                    "We report V_circ together with amp_min and bootstrap CIs to separate structural non-flatness from measurement-quality artifacts.",
                    "We interpret η3 sweep as a controlled stress-test family, not as a device model claim.",
                ],
            ),
        ),
        outputs=outputs,
    )
