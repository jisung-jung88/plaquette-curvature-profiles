# fig4_sim_data.py
# Build a SIMULATION analogue of Fig.6 (QPU η3 sweep grid).
#
# Target figure: 3x2 grid of κ-profiles
#   rows   : η3 ∈ {0, 0.1, 0.2}
#   cols   : signal / control
# Each panel shows:
#   - κ̂(z_rest) over contexts (z_rest_int)
#   - amp_min(z_rest) = min(amp_a, amp_b) as a quality diagnostic
#   - a horizontal dotted line at the context-collapsed effective phase
#       κ_eff = arg ⟨exp(i κ̂)⟩_contexts
#
# This is meant to mirror the QPU-side Fig.6 data product (fig4_data.py),
# but uses simulation artifacts (rows + trial_summary CSV).

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Small utilities
# -----------------------------------------------------------------------------


def file_sha256(path: Path, chunk_bytes: int = 1 << 20) -> str:
    """Compute SHA256 of a file (streaming; safe for large CSVs)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_bytes)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def wrap_to_pi(x: np.ndarray) -> np.ndarray:
    """Wrap angles to (-pi, pi]."""
    return (x + np.pi) % (2 * np.pi) - np.pi


def circular_mean_and_R(angles_rad: np.ndarray) -> Tuple[float, float]:
    """Return (circular mean angle, resultant length R)."""
    if angles_rad.size == 0:
        return (float("nan"), float("nan"))
    ph = np.exp(1j * angles_rad.astype(float))
    m = ph.mean()
    return (float(np.angle(m)), float(np.abs(m)))


def _validate_pair(pair: Tuple[int, int]) -> Tuple[int, int]:
    i, j = pair
    if not (isinstance(i, int) and isinstance(j, int)):
        raise TypeError(f"Pair must be (int,int), got {pair!r}")
    if i == j:
        raise ValueError(f"Pair must have i!=j, got {pair!r}")
    return (i, j) if i < j else (j, i)


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Fig6SimAnalysisConfig:
    """Analysis hyperparameters (recorded for reproducibility)."""

    # Trial selection
    trial_policy: str = "median_by_signal"  # "fixed" | "median_by_signal"
    trial_id: Optional[int] = None
    trial_select_eta3: float = 0.2  # eta used to choose representative trial

    # Data interpretation
    wrap_phase_to_pi: bool = True

    # Quality filter (optional)
    amp_min_threshold: float = 0.0

    # Column names (simulation rows CSV)
    col_kappa_hat: str = "kappa_hat"
    col_kappa_true: str = "kappa_true"
    col_amp_a: str = "amp_a"
    col_amp_b: str = "amp_b"


# -----------------------------------------------------------------------------
# Core logic
# -----------------------------------------------------------------------------


def select_trial_id(
    trial_df: pd.DataFrame,
    *,
    eta3: float,
    n: int,
    signal_pair: Tuple[int, int],
    policy: str,
    fixed_trial_id: Optional[int],
) -> int:
    """Choose a representative trial_id.

    - fixed: uses fixed_trial_id (must exist)
    - median_by_signal: pick trial whose V_circ is closest to the median V_circ
      for the SIGNAL pair at (eta3, n).
    """
    policy = policy.lower().strip()
    (si, sj) = _validate_pair(signal_pair)

    df = trial_df[
        (trial_df["eta3"] == float(eta3))
        & (trial_df["n"] == int(n))
        & (trial_df["i"] == int(si))
        & (trial_df["j"] == int(sj))
    ].copy()

    if df.empty:
        raise ValueError(f"No trials found for eta3={eta3}, n={n}, signal_pair=({si},{sj}).")

    if policy == "fixed":
        if fixed_trial_id is None:
            raise ValueError("trial_policy='fixed' requires cfg.trial_id to be set.")
        if int(fixed_trial_id) not in set(df["trial_id"].astype(int).tolist()):
            raise ValueError(
                f"Requested trial_id={fixed_trial_id} not present for eta3={eta3}, n={n}, signal_pair=({si},{sj})."
            )
        return int(fixed_trial_id)

    if policy == "median_by_signal":
        v = df["kappa_ctx_circ_var_trial"].astype(float).to_numpy()
        med = float(np.median(v))
        df["dist"] = (df["kappa_ctx_circ_var_trial"].astype(float) - med).abs()
        # deterministic tie-break: smallest trial_id
        df = df.sort_values(["dist", "trial_id"], ascending=[True, True])
        return int(df.iloc[0]["trial_id"])

    raise ValueError(f"Unsupported trial_policy={policy!r} (use 'fixed' or 'median_by_signal').")


def extract_profile_df(
    rows_df: pd.DataFrame,
    *,
    eta3: float,
    n: int,
    pair: Tuple[int, int],
    trial_id: int,
    cfg: Fig6SimAnalysisConfig,
) -> pd.DataFrame:
    """Return per-context profile df for a given (eta3,n,pair,trial_id)."""
    (i, j) = _validate_pair(pair)

    df = rows_df[
        (rows_df["eta3"] == float(eta3))
        & (rows_df["n"] == int(n))
        & (rows_df["i"] == int(i))
        & (rows_df["j"] == int(j))
        & (rows_df["trial_id"] == int(trial_id))
    ].copy()

    if df.empty:
        raise ValueError(f"No rows found for eta3={eta3}, n={n}, pair=({i},{j}), trial_id={trial_id}.")

    # Quality per context
    df["amp_min_ctx"] = np.minimum(df[cfg.col_amp_a].astype(float), df[cfg.col_amp_b].astype(float))

    # Wrap phase if requested
    kh = df[cfg.col_kappa_hat].astype(float).to_numpy()
    if cfg.wrap_phase_to_pi:
        kh = wrap_to_pi(kh)
    df["kappa_hat"] = kh

    # Optional true value
    if cfg.col_kappa_true in df.columns:
        kt = df[cfg.col_kappa_true].astype(float).to_numpy()
        if cfg.wrap_phase_to_pi:
            kt = wrap_to_pi(kt)
        df["kappa_true"] = kt

    keep_cols = ["eta3", "n", "i", "j", "trial_id", "z_rest_int", "kappa_hat", "amp_min_ctx"]
    if "kappa_true" in df.columns:
        keep_cols.append("kappa_true")

    df = df[keep_cols].sort_values("z_rest_int").reset_index(drop=True)
    df["z_rest_int"] = df["z_rest_int"].astype(int)
    return df


def compute_panel_stats(dfp: pd.DataFrame, *, cfg: Fig6SimAnalysisConfig) -> Dict[str, float]:
    """Compute κ_eff and helper scalars for a single panel."""
    mask = np.isfinite(dfp["kappa_hat"].to_numpy(float))
    if cfg.amp_min_threshold > 0.0:
        mask = mask & (dfp["amp_min_ctx"].to_numpy(float) >= float(cfg.amp_min_threshold))

    kappa = dfp.loc[mask, "kappa_hat"].to_numpy(float)
    kappa_eff, R = circular_mean_and_R(kappa)
    V = float("nan") if not math.isfinite(R) else float(np.clip(1.0 - R, 0.0, 1.0))

    # parking scalar: κ̂ at z_rest_int=0 (if present)
    kappa_parking = float("nan")
    if (dfp["z_rest_int"] == 0).any():
        v0 = dfp.loc[dfp["z_rest_int"] == 0, "kappa_hat"].to_numpy(float)
        if v0.size:
            kappa_parking = float(v0[0])

    # q90(|κ|) over contexts (after mask)
    q90_abs = float("nan")
    if kappa.size:
        q90_abs = float(np.quantile(np.abs(wrap_to_pi(kappa)), 0.90))

    return dict(
        kappa_eff=float(kappa_eff),
        V_circ=float(V),
        kappa_parking=float(kappa_parking),
        q90_abs=float(q90_abs),
        num_contexts_total=int(len(dfp)),
        num_contexts_used=int(mask.sum()),
    )


def compute_fig4_sim_products(
    *,
    trial_summary_csv: Path,
    rows_csv: Path,
    cfg: Fig6SimAnalysisConfig,
    eta_values: Tuple[float, float, float] = (0.0, 0.1, 0.2),
    profile_n: int = 7,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (2, 3),
) -> Dict[str, Any]:
    """Main entry point for simulation Fig.6.

    Returns:
      {
        "panel_df": per-context rows for all 6 panels,
        "panel_stats_df": per-panel scalars,
        "chosen_trial_id": int,
      }
    """
    trial_df = pd.read_csv(trial_summary_csv)
    rows_df = pd.read_csv(rows_csv)

    # Basic schema checks
    required_trial_cols = {"eta3", "n", "i", "j", "trial_id", "kappa_ctx_circ_var_trial"}
    missing = required_trial_cols - set(trial_df.columns)
    if missing:
        raise ValueError(f"trial_summary_csv missing columns: {sorted(missing)}")

    required_rows_cols = {"eta3", "n", "i", "j", "trial_id", "z_rest_int", cfg.col_kappa_hat, cfg.col_amp_a, cfg.col_amp_b}
    missing = required_rows_cols - set(rows_df.columns)
    if missing:
        raise ValueError(f"rows_csv missing columns: {sorted(missing)}")

    # Normalize pairs
    signal_pair_n = _validate_pair(signal_pair)
    control_pair_n = _validate_pair(control_pair)

    # Choose a representative trial (single trial across all eta values)
    chosen_trial_id = select_trial_id(
        trial_df,
        eta3=float(cfg.trial_select_eta3),
        n=int(profile_n),
        signal_pair=signal_pair_n,
        policy=str(cfg.trial_policy),
        fixed_trial_id=int(cfg.trial_id) if cfg.trial_id is not None else None,
    )

    panel_specs = [
        ("signal", signal_pair_n),
        ("control", control_pair_n),
    ]

    panel_rows: List[pd.DataFrame] = []
    panel_stats_records: List[Dict[str, Any]] = []

    for eta in eta_values:
        for role, pair in panel_specs:
            dfp = extract_profile_df(
                rows_df,
                eta3=float(eta),
                n=int(profile_n),
                pair=pair,
                trial_id=int(chosen_trial_id),
                cfg=cfg,
            )

            stats = compute_panel_stats(dfp, cfg=cfg)
            panel_stats_records.append(
                dict(
                    eta3=float(eta),
                    role=str(role),
                    n=int(profile_n),
                    pair=f"({pair[0]},{pair[1]})",
                    i=int(pair[0]),
                    j=int(pair[1]),
                    trial_id=int(chosen_trial_id),
                    **stats,
                )
            )

            dfp2 = dfp.copy()
            dfp2["role"] = str(role)
            dfp2["pair"] = f"({pair[0]},{pair[1]})"
            dfp2["has_all_settings"] = True  # Simulation rows always have all settings
            panel_rows.append(dfp2)

    panel_df = pd.concat(panel_rows, ignore_index=True) if panel_rows else pd.DataFrame()
    panel_stats_df = (
        pd.DataFrame(panel_stats_records)
        .sort_values(["eta3", "role"], ascending=[True, True])
        .reset_index(drop=True)
    )

    return dict(
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        chosen_trial_id=int(chosen_trial_id),
    )


def build_fig4_sim_manifest(
    *,
    trial_summary_csv: Path,
    rows_csv: Path,
    cfg: Fig6SimAnalysisConfig,
    panel_df: pd.DataFrame,
    panel_stats_df: pd.DataFrame,
    outputs: Dict[str, str],
    eta_values: Tuple[float, float, float] = (0.0, 0.1, 0.2),
    profile_n: int = 7,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (2, 3),
    run_meta_json: Optional[Path] = None,
    stats_meta_json: Optional[Path] = None,
    style_rcparams: Optional[Dict[str, Any]] = None,
    fig_size_inches: Tuple[float, float] = (10.0, 9.0),
    panel_colors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Machine-readable figure spec for simulation Fig.6."""
    if panel_colors is None:
        panel_colors = {}

    def _panel_records() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in panel_stats_df.itertuples(index=False):
            dfp = panel_df[
                (panel_df["eta3"] == float(r.eta3))
                & (panel_df["role"] == str(r.role))
                & (panel_df["n"] == int(r.n))
                & (panel_df["pair"] == str(r.pair))
                & (panel_df["trial_id"] == int(r.trial_id))
            ].sort_values("z_rest_int")

            rec: Dict[str, Any] = dict(
                eta3=float(r.eta3),
                role=str(r.role),
                n=int(r.n),
                pair=str(r.pair),
                trial_id=int(r.trial_id),
                x_z_rest_int=dfp["z_rest_int"].astype(int).tolist(),
                kappa_hat_rad=dfp["kappa_hat"].astype(float).tolist(),
                amp_min=dfp["amp_min_ctx"].astype(float).tolist(),
                has_all_settings=dfp["has_all_settings"].astype(bool).tolist(),
                kappa_eff_rad=float(r.kappa_eff),
                V_circ=float(r.V_circ),
                kappa_parking_rad=float(r.kappa_parking),
                q90_abs_rad=float(r.q90_abs),
                num_contexts_total=int(r.num_contexts_total),
                num_contexts_used=int(r.num_contexts_used),
            )
            if "kappa_true" in dfp.columns:
                rec["kappa_true_rad"] = dfp["kappa_true"].astype(float).tolist()
            out.append(rec)
        return out

    inputs_dict: Dict[str, Any] = dict(
        trial_summary_csv=dict(path=str(trial_summary_csv), sha256=file_sha256(trial_summary_csv)),
        rows_csv=dict(path=str(rows_csv), sha256=file_sha256(rows_csv)),
    )
    if run_meta_json is not None:
        inputs_dict["run_meta_json"] = dict(path=str(run_meta_json), sha256=file_sha256(run_meta_json))
    if stats_meta_json is not None:
        inputs_dict["stats_meta_json"] = dict(path=str(stats_meta_json), sha256=file_sha256(stats_meta_json))

    # Outputs: include sha256 when available
    out_payload: Dict[str, Any] = {}
    for k, v in outputs.items():
        if v is None:
            continue
        p = Path(v)
        out_payload[k] = dict(path=str(p), sha256=file_sha256(p) if p.exists() else None)

    return dict(
        figure_id="Fig4_SIM",
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        inputs=inputs_dict,
        analysis_config=asdict(cfg),
        layout=dict(
            figure_size_inches=list(fig_size_inches),
            grid=dict(rows=3, cols=2),
            eta_values=[float(x) for x in eta_values],
            profile_n=int(profile_n),
            signal_pair=list(_validate_pair(signal_pair)),
            control_pair=list(_validate_pair(control_pair)),
            style=dict(
                rcParams=style_rcparams if style_rcparams is not None else {},
                panel_colors=dict(panel_colors),
            ),
        ),
        outputs=out_payload,
        data=dict(
            panels=_panel_records(),
            notes=dict(
                kappa_eff_definition="kappa_eff = arg < exp(i * kappa_hat) >_contexts",
                trial_selection_note=(
                    f"trial_policy={cfg.trial_policy}; trial_select_eta3={cfg.trial_select_eta3}; trial_id={cfg.trial_id}"
                ),
            ),
        ),
    )
