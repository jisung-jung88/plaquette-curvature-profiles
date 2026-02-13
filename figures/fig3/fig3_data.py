# fig3_data.py
# Data loading + aggregation for Fig.3 (Simulation scaling report).
#
# Goal:
# - Keep "data generation" separate from "plot styling" (see fig3_plot.py).
# - Accept the 4 simulation artifacts (2 CSV + 2 JSON) as inputs.
# - Produce:
#     * summary_df: per-(eta3, n, pair) aggregated metrics + bootstrap CI over trials
#     * delta_df: ΔV_circ = V_circ(signal) - V_circ(control)
#     * manifest dict (machine-readable figure spec)

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import hashlib
import json

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def file_sha256(path: Path, chunk_bytes: int = 1 << 20) -> str:
    """Compute SHA256 of a file (streaming; safe for large CSV)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_bytes)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def stable_int_hash(s: str) -> int:
    """
    Deterministic 32-bit-ish hash for seeding RNG per group (avoid Python's randomized hash()).
    """
    h = hashlib.sha256(s.encode("utf-8")).digest()
    # Take first 8 bytes for a 64-bit int, then fold down.
    x = int.from_bytes(h[:8], byteorder="little", signed=False)
    return int(x % (2**32))


def require_columns(df: pd.DataFrame, required: Iterable[str], *, df_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"[{df_name}] Missing required columns: {missing}\n"
            f"Available columns: {list(df.columns)}"
        )


def parse_pair_str(pair: str) -> Tuple[int, int]:
    """Parse '(i,j)' into (i,j)."""
    p = pair.strip()
    if not (p.startswith("(") and p.endswith(")")):
        raise ValueError(f"Bad pair string: {pair}")
    body = p[1:-1]
    a, b = body.split(",")
    return int(a), int(b)


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Fig3AnalysisConfig:
    # Bootstrap over trials (NOT shot bootstrap; trial-to-trial resampling)
    boot_B: int = 5000
    seed: int = 12345
    ci_levels: Tuple[float, float] = (0.025, 0.975)

    # Point estimator used for V_circ in plots.
    # - "trial": raw sample mean over trials
    # - "boot_median": median of bootstrap distribution (reviewer-proof: point lies inside CI)
    # - "boot_mean": mean of bootstrap distribution (≈ sample mean)
    point_estimator: str = "boot_median"

    # Statistic used inside bootstrap resamples.
    # In most cases we want "mean" across trials.
    bootstrap_stat: str = "mean"


# -----------------------------------------------------------------------------
# Loaders
# -----------------------------------------------------------------------------

def load_trial_summary_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    require_columns(
        df,
        required=[
            "run_id",
            "eta3",
            "n",
            "i",
            "j",
            "trial_id",
            "num_contexts",
            "kappa_ctx_circ_var_trial",
            "amp_min_mean_ctx_trial",
            "amp_min_q10_ctx_trial",
            "shots_per_setting",
        ],
        df_name="trial_summary",
    )

    # Normalize dtypes
    df = df.copy()
    df["eta3"] = df["eta3"].astype(float)
    df["n"] = df["n"].astype(int)
    df["i"] = df["i"].astype(int)
    df["j"] = df["j"].astype(int)
    df["trial_id"] = df["trial_id"].astype(int)
    df["num_contexts"] = df["num_contexts"].astype(int)
    df["shots_per_setting"] = df["shots_per_setting"].astype(int)

    # Pair label used throughout figures
    df["pair"] = df.apply(lambda r: f"({int(r['i'])},{int(r['j'])})", axis=1)

    return df


def load_rows_csv_minimal(path: Path, *, nrows: int = 5) -> pd.DataFrame:
    """
    Fig.3 does not need the full rows table, but we still sanity-check that the
    file exists and has the expected columns without loading the entire CSV.
    """
    df = pd.read_csv(path, nrows=nrows)
    require_columns(
        df,
        required=["eta3", "n", "i", "j", "z_rest_int", "trial_id", "kappa_hat", "amp_a", "amp_b"],
        df_name="rows_csv",
    )
    return df


# -----------------------------------------------------------------------------
# Bootstrap aggregation
# -----------------------------------------------------------------------------

def bootstrap_ci_over_trials(
    values: np.ndarray,
    *,
    cfg: Fig3AnalysisConfig,
    seed_key: str,
) -> Dict[str, float]:
    """
    Bootstrap CI over trial-level values.

    Returns dict with:
      - raw_mean
      - boot_mean
      - boot_median
      - ci_lo
      - ci_hi
      - point (as per cfg.point_estimator)
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return dict(
            raw_mean=float("nan"),
            boot_mean=float("nan"),
            boot_median=float("nan"),
            ci_lo=float("nan"),
            ci_hi=float("nan"),
            point=float("nan"),
        )

    # Group-specific RNG (deterministic)
    seed = int(cfg.seed + stable_int_hash(seed_key)) % (2**32)
    rng = np.random.default_rng(seed)

    n = int(values.size)
    B = int(cfg.boot_B)

    # Resample indices (B, n)
    idx = rng.integers(0, n, size=(B, n))
    samples = values[idx]

    stat = cfg.bootstrap_stat.lower().strip()
    if stat == "mean":
        boot_stats = samples.mean(axis=1)
        raw = float(values.mean())
    elif stat == "median":
        boot_stats = np.median(samples, axis=1)
        raw = float(np.median(values))
    else:
        raise ValueError(f"Unsupported bootstrap_stat={cfg.bootstrap_stat!r} (use 'mean' or 'median')")

    ci_lo, ci_hi = np.quantile(boot_stats, cfg.ci_levels).astype(float).tolist()
    boot_mean = float(np.mean(boot_stats))
    boot_median = float(np.median(boot_stats))

    pe = cfg.point_estimator.lower().strip()
    if pe == "trial":
        point = raw
    elif pe == "boot_median":
        point = boot_median
    elif pe == "boot_mean":
        point = boot_mean
    else:
        raise ValueError(f"Unsupported point_estimator={cfg.point_estimator!r}")

    return dict(
        raw_mean=raw,
        boot_mean=boot_mean,
        boot_median=boot_median,
        ci_lo=float(ci_lo),
        ci_hi=float(ci_hi),
        point=float(point),
    )


def compute_fig3_summary(
    trial_df: pd.DataFrame,
    *,
    cfg: Fig3AnalysisConfig,
) -> pd.DataFrame:
    """
    Aggregate trial_summary.csv into one row per (eta3, n, i, j).
    """
    rows: List[Dict[str, Any]] = []

    group_cols = ["eta3", "n", "i", "j"]
    for (eta3, n, i, j), g in trial_df.groupby(group_cols):
        pair = f"({int(i)},{int(j)})"
        run_id = str(g["run_id"].iloc[0])
        shots_per_setting = int(g["shots_per_setting"].iloc[0])
        num_contexts = int(g["num_contexts"].iloc[0])
        num_trials = int(g["trial_id"].nunique())

        V_vals = g["kappa_ctx_circ_var_trial"].to_numpy(float)
        boot = bootstrap_ci_over_trials(
            V_vals,
            cfg=cfg,
            seed_key=f"eta3={float(eta3)}|n={int(n)}|i={int(i)}|j={int(j)}|run_id={run_id}",
        )

        # For Fig.3, we follow Fig.5 conventions for column naming:
        # - kappa_ctx_circ_var_trial: the raw point (here: sample mean over trials)
        # - kappa_ctx_circ_var_point: reviewer-proof point estimator (bootstrap median by default)
        # - kappa_ctx_circ_var_ci95_lo/hi: CI95 over trials (bootstrap)
        amp_mean = float(np.mean(g["amp_min_mean_ctx_trial"].to_numpy(float)))
        amp_q10 = float(np.mean(g["amp_min_q10_ctx_trial"].to_numpy(float)))

        rows.append(
            dict(
                run_id=run_id,
                eta3=float(eta3),
                n=int(n),
                i=int(i),
                j=int(j),
                pair=pair,
                num_trials=num_trials,
                shots_per_setting=shots_per_setting,
                num_contexts=num_contexts,
                # V_circ
                kappa_ctx_circ_var_trial=float(boot["raw_mean"]),
                kappa_ctx_circ_var_point=float(boot["point"]),
                kappa_ctx_circ_var_boot_mean=float(boot["boot_mean"]),
                kappa_ctx_circ_var_boot_median=float(boot["boot_median"]),
                kappa_ctx_circ_var_ci95_lo=float(boot["ci_lo"]),
                kappa_ctx_circ_var_ci95_hi=float(boot["ci_hi"]),
                # Quality (amp_min)
                amp_min_mean_ctx_trial=amp_mean,
                amp_min_q10_ctx_trial=amp_q10,
            )
        )

    summary_df = pd.DataFrame(rows).sort_values(["eta3", "pair", "n"]).reset_index(drop=True)
    return summary_df


def compute_deltaV(
    summary_df: pd.DataFrame,
    *,
    signal_pair: Tuple[int, int],
    control_pair: Tuple[int, int],
) -> pd.DataFrame:
    """
    Compute ΔV = V(signal) - V(control) for each (eta3, n) where both exist.
    """
    sp = f"({signal_pair[0]},{signal_pair[1]})"
    cp = f"({control_pair[0]},{control_pair[1]})"

    sig = summary_df[summary_df["pair"] == sp].copy()
    ctl = summary_df[summary_df["pair"] == cp].copy()

    key = ["eta3", "n"]
    keep_cols = [
        "kappa_ctx_circ_var_point",
        "kappa_ctx_circ_var_trial",
        "kappa_ctx_circ_var_ci95_lo",
        "kappa_ctx_circ_var_ci95_hi",
    ]
    sig = sig[key + keep_cols].rename(columns={c: f"signal_{c}" for c in keep_cols})
    ctl = ctl[key + keep_cols].rename(columns={c: f"control_{c}" for c in keep_cols})

    merged = sig.merge(ctl, on=key, how="inner").sort_values(key).reset_index(drop=True)
    merged["deltaV_point"] = merged["signal_kappa_ctx_circ_var_point"] - merged["control_kappa_ctx_circ_var_point"]
    merged["deltaV_trial"] = merged["signal_kappa_ctx_circ_var_trial"] - merged["control_kappa_ctx_circ_var_trial"]

    # CI for delta is not trivial without paired bootstrap. We leave it out by default.
    return merged


# -----------------------------------------------------------------------------
# Main products + manifest
# -----------------------------------------------------------------------------

def compute_fig3_products(
    *,
    trial_summary_csv: Path,
    rows_csv: Path,
    run_meta_json: Path,
    stats_meta_json: Path,
    cfg: Fig3AnalysisConfig,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (2, 3),
) -> Dict[str, Any]:
    """
    Entry point for Fig.3 values generation.
    """
    trial_df = load_trial_summary_csv(trial_summary_csv)

    # Light sanity check for rows.csv (do not load full file for Fig.3)
    _ = load_rows_csv_minimal(rows_csv, nrows=5)

    summary_df = compute_fig3_summary(trial_df, cfg=cfg)
    delta_df = compute_deltaV(summary_df, signal_pair=signal_pair, control_pair=control_pair)

    return dict(
        trial_df=trial_df,
        summary_df=summary_df,
        delta_df=delta_df,
    )


def build_fig3_manifest(
    *,
    trial_summary_csv: Path,
    rows_csv: Path,
    run_meta_json: Path,
    stats_meta_json: Path,
    cfg: Fig3AnalysisConfig,
    summary_df: pd.DataFrame,
    outputs: Dict[str, str],
    style_rcparams: Optional[Dict[str, Any]] = None,
    fig_size_inches: Tuple[float, float] = (10.0, 3.6),
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (2, 3),
) -> Dict[str, Any]:
    """Machine-readable figure spec for Fig.3 (Simulation scaling report)."""

    eta_vals = [float(x) for x in sorted(summary_df["eta3"].unique())]
    ns = [int(x) for x in sorted(summary_df["n"].unique())]

    # Use the same lightweight style encoding scheme as Fig.5 manifest.
    palette = ["tab:blue", "tab:orange", "tab:green", "tab:purple", "tab:brown"]
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
                        y_V_circ=df["kappa_ctx_circ_var_point"].astype(float).tolist(),
                        y_V_circ_trial=df["kappa_ctx_circ_var_trial"].astype(float).tolist(),
                        ci95_lo=df["kappa_ctx_circ_var_ci95_lo"].astype(float).tolist(),
                        ci95_hi=df["kappa_ctx_circ_var_ci95_hi"].astype(float).tolist(),
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
        trial_summary_csv=dict(path=str(trial_summary_csv), sha256=file_sha256(trial_summary_csv)),
        rows_csv=dict(path=str(rows_csv), sha256=file_sha256(rows_csv)),
        run_meta_json=dict(path=str(run_meta_json), sha256=file_sha256(run_meta_json)),
        stats_meta_json=dict(path=str(stats_meta_json), sha256=file_sha256(stats_meta_json)),
    )

    return dict(
        figure_id="Fig3",
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
                        axes_labelsize=13,
                        xtick_labelsize=10,
                        ytick_labelsize=10,
                        legend_fontsize=10,
                        axes_grid=True,
                        grid_alpha=0.3,
                        grid_linestyle="-",
                    )
                )
            ),
        ),
        data=dict(
            n_values=ns,
            eta3_values=eta_vals,
            signal_pair=f"({signal_pair[0]},{signal_pair[1]})",
            control_pair=f"({control_pair[0]},{control_pair[1]})",
            panel_A_traces=_panelA_traces(),
            panel_B_traces=_panelB_traces(),
            notes=dict(
                caption_must_include=[
                    "η3 is a controlled residue-injection knob; η3=0 is a negative control and η3>0 forms a positive-control family.",
                    "Plateaus / weak n-dependence in dispersion are interpreted as locality-limited spectator influence, not as failure of the method.",
                ],
                ci_note="CI95 is computed by bootstrap resampling over trials (not shot bootstrap).",
            ),
        ),
        outputs=outputs,
    )
