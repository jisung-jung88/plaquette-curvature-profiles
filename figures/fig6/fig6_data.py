# fig6_data.py
# Build Fig.6 data products from TWO inputs:
#   (1) combined counts JSON
#   (2) combined run_meta JSON
#
# Fig.6 is a 3x2 grid of kappa-profiles (eta3 rows; signal/control columns)
# with a horizontal dotted line showing the context-collapsed effective phase
#   kappa_eff = arg < exp(i * kappa_hat(z_rest)) >_{z_rest}.
#
# Plotting is handled separately by fig6_plot.py.

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
# NOTE (2026-01-08):
# This file is intentionally self-contained.
# The Fig.6 generator originally imported JSON parsing + run-selection helpers
# from qpu_data.py (Fig.5 generator). To make Fig.6 runnable with a single file,
# we inline the minimal subset of utilities here.
# -----------------------------------------------------------------------------

REQUIRED_SETTINGS: Tuple[str, str, str, str] = ("cos_a", "sin_a", "cos_b", "sin_b")


@dataclass
class Fig6AnalysisConfig:
    """Analysis hyperparameters (recorded for reproducibility)."""

    amp_min_threshold: float = 0.0


# -----------------------------------------------------------------------------
# Basic IO + run-selection helpers (inlined from qpu_data.py)
# -----------------------------------------------------------------------------

def file_sha256(path: Path, blocksize: int = 1 << 20) -> str:
    """Compute SHA256 for provenance tracking in figure manifests."""

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(blocksize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_combined_counts(path: Path) -> pd.DataFrame:
    """Parse a combined counts JSON into a long-form DataFrame.

    Output columns:
      eta3, run, n, i, j, z_rest_int, setting, shots, c0, c1, bit_order

    Supported payload schemas:
      - counts.v1 (single pair per payload)
      - counts.v2 (pair stored per record)

    Supported wrapper formats:
      - list of {eta3, run, data:[payloads...]}
      - a single payload dict (back-compat)
    """

    obj = json.loads(path.read_text())

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

    df["eta3"] = df["eta3"].astype(float)
    for c in ["n", "i", "j", "z_rest_int", "shots", "c0", "c1"]:
        df[c] = df[c].astype(int)
    df["setting"] = df["setting"].astype(str)
    df["bit_order"] = df["bit_order"].astype(str)
    return df


def load_combined_run_meta(path: Path) -> List[Dict[str, Any]]:
    """Return the combined run_meta JSON as a list of eta blocks."""

    obj = json.loads(path.read_text())
    if isinstance(obj, list):
        return obj
    return [{"eta3": float(obj.get("eta3", 0.0)), "run": obj.get("run", ""), "data": [obj]}]


def _eta_key(x: float) -> float:
    """Canonical eta3 key used for matching CLI vs JSON values."""

    return round(float(x), 12)


def _normalize_run(run: Any) -> str:
    """Normalize run values (int/float/str) into a stable string for matching."""

    if run is None:
        return ""

    # numpy scalar ints
    try:
        import numpy as _np

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
    """Filter counts_df to keep only the selected run per eta3.

    Requirements:
      - If a requested (eta3, run) does not exist, raise immediately.
      - If eta3 is not in eta_run_selection, keep all its runs.
    """

    if not eta_run_selection:
        return counts_df

    df = counts_df.copy()
    df["_eta_key"] = df["eta3"].map(_eta_key)
    df["_run_norm"] = df["run"].map(_normalize_run)

    avail = set(zip(df["_eta_key"].tolist(), df["_run_norm"].tolist()))

    # Validate requested pairs exist.
    for eta_k, run_req in eta_run_selection.items():
        ek = _eta_key(eta_k)
        rn = _normalize_run(run_req)
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
        rn = _normalize_run(run_req)
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
    sel_norm: Dict[float, str] = {_eta_key(float(k)): _normalize_run(v) for k, v in eta_run_selection.items()}
    sel_keys = set(sel_norm.keys())

    avail = {(_eta_key(float(blk.get("eta3", 0.0))), _normalize_run(blk.get("run", ""))) for blk in run_meta_blocks}

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
        rn = _normalize_run(blk.get("run", ""))
        if ek in sel_keys:
            if rn == sel_norm[ek]:
                out.append(blk)
        else:
            out.append(blk)

    return out


def build_context_table(counts_df: pd.DataFrame) -> pd.DataFrame:
    """Context-level point estimates from raw counts.

    Per (eta3,n,i,j,z_rest_int), compute:
      - expectations m for each setting
      - kappa_hat (phasor estimator)
      - amp metrics, and has_all_settings
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


# -----------------------------------------------------------------------------
# Fig.6-specific logic
# -----------------------------------------------------------------------------

def auto_select_eta_runs(
    counts_df: pd.DataFrame,
    *,
    eta_values: Optional[List[float]] = None,
) -> Dict[float, Any]:
    """Pick a deterministic single run per eta3 if multiple runs are present.

    Heuristic: choose the run with the largest number of rows for each eta3.
    Tie-break: lexicographic order of normalized run string.
    """

    if eta_values is None:
        eta_values = sorted({float(x) for x in counts_df["eta3"].unique()})

    sel: Dict[float, Any] = {}
    for eta in eta_values:
        g = counts_df[counts_df["eta3"] == float(eta)]
        runs = sorted({_normalize_run(x) for x in g["run"].unique()})
        if len(runs) <= 1:
            continue

        sizes = (
            g.assign(_run_norm=g["run"].map(_normalize_run))
            .groupby("_run_norm", dropna=False)
            .size()
            .sort_values(ascending=False)
        )
        best_size = int(sizes.iloc[0])
        best_runs = sorted([r for r, s in sizes.items() if int(s) == best_size])
        best_run_norm = best_runs[0]

        # Map back to original run value if possible (use first matching)
        best_orig = g[g["run"].map(_normalize_run) == best_run_norm]["run"].iloc[0]
        sel[_eta_key(eta)] = best_orig

    return sel


def compute_panel_stats(
    dfp: pd.DataFrame,
    *,
    cfg: Fig6AnalysisConfig,
) -> Dict[str, float]:
    """Compute kappa_eff and helper scalars for a single panel."""

    mask = dfp["has_all_settings"].to_numpy(bool) & np.isfinite(dfp["kappa_hat"].to_numpy(float))
    if cfg.amp_min_threshold > 0.0:
        mask = mask & (dfp["amp_min_ctx"].to_numpy(float) >= float(cfg.amp_min_threshold))

    kappa = dfp.loc[mask, "kappa_hat"].to_numpy(float)
    kappa_eff, R = circular_mean_and_R(kappa)
    V = float("nan") if not math.isfinite(R) else float(np.clip(1.0 - R, 0.0, 1.0))

    # parking scalar: kappa_hat at z_rest_int=0 (if present)
    kappa_parking = float("nan")
    if (dfp["z_rest_int"] == 0).any():
        v0 = dfp.loc[dfp["z_rest_int"] == 0, "kappa_hat"].to_numpy(float)
        if v0.size:
            kappa_parking = float(v0[0])

    # q90(|kappa|) over contexts (after mask)
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


def compute_fig6_products(
    *,
    counts_json: Path,
    run_meta_json: Path,
    cfg: Fig6AnalysisConfig,
    eta_values: Tuple[float, float, float] = (0.0, 0.1, 0.2),
    profile_n: int = 7,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
    eta_run_selection: Optional[Dict[float, Any]] = None,
    auto_select_runs_if_missing: bool = True,
) -> Dict[str, Any]:
    """Main entry point for Fig.6 (values generation).

    Returns:
      {
        "counts_df": long counts df (filtered to a single run per eta3),
        "context_df": context-level point df,
        "panel_df": concatenated per-panel context rows with role/pair labels,
        "panel_stats_df": per-panel scalars (kappa_eff, V_circ, etc),
        "eta_run_selection_used": dict(eta3->run) actually applied,
      }
    """

    counts_df = load_combined_counts(counts_json)
    run_meta_blocks = load_combined_run_meta(run_meta_json)

    # Decide run selection.
    eta_run_sel_used: Dict[float, Any] = {}
    if eta_run_selection:
        eta_run_sel_used = {_eta_key(k): v for k, v in eta_run_selection.items()}
    elif auto_select_runs_if_missing:
        eta_run_sel_used = auto_select_eta_runs(counts_df, eta_values=list(eta_values))

    if eta_run_sel_used:
        counts_df = apply_eta_run_selection_to_counts(counts_df, eta_run_sel_used, counts_json=counts_json)
        # Keep this call to validate we didn't select a run absent from run_meta.
        run_meta_blocks = apply_eta_run_selection_to_run_meta(run_meta_blocks, eta_run_sel_used, run_meta_json=run_meta_json)

    # Build context table (phasor kappa_hat, amp metrics, has_all_settings)
    context_df = build_context_table(counts_df)

    # Construct per-panel data
    panel_specs = [
        ("signal", signal_pair[0], signal_pair[1]),
        ("control", control_pair[0], control_pair[1]),
    ]

    panels: List[Dict[str, Any]] = []
    panel_rows: List[pd.DataFrame] = []

    for eta in eta_values:
        for role, i, j in panel_specs:
            dfp = context_df[
                (context_df["eta3"] == float(eta))
                & (context_df["n"] == int(profile_n))
                & (context_df["i"] == int(i))
                & (context_df["j"] == int(j))
            ].sort_values("z_rest_int")
            if dfp.empty:
                continue

            stats = compute_panel_stats(dfp, cfg=cfg)
            panels.append(
                dict(
                    eta3=float(eta),
                    role=str(role),
                    n=int(profile_n),
                    pair=f"({int(i)},{int(j)})",
                    i=int(i),
                    j=int(j),
                    **stats,
                )
            )

            dfp2 = dfp.copy()
            dfp2["role"] = str(role)
            dfp2["pair"] = f"({int(i)},{int(j)})"
            panel_rows.append(dfp2)

    panel_df = pd.concat(panel_rows, ignore_index=True) if panel_rows else pd.DataFrame()
    panel_stats_df = pd.DataFrame(panels).sort_values(["eta3", "role"]).reset_index(drop=True)

    return dict(
        counts_df=counts_df,
        context_df=context_df,
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        eta_run_selection_used=eta_run_sel_used,
    )


def build_fig6_manifest(
    *,
    counts_json: Path,
    run_meta_json: Path,
    cfg: Fig6AnalysisConfig,
    panel_df: pd.DataFrame,
    panel_stats_df: pd.DataFrame,
    outputs: Dict[str, str],
    eta_values: Tuple[float, float, float] = (0.0, 0.1, 0.2),
    profile_n: int = 7,
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
    eta_run_selection_used: Optional[Dict[float, Any]] = None,
    style_rcparams: Optional[Dict[str, Any]] = None,
    fig_size_inches: Tuple[float, float] = (10.0, 9.0),
    panel_colors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Machine-readable figure spec for Fig.6."""

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
            ].sort_values("z_rest_int")

            out.append(
                dict(
                    eta3=float(r.eta3),
                    role=str(r.role),
                    n=int(r.n),
                    pair=str(r.pair),
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
            )
        return out

    inputs_dict: Dict[str, Any] = dict(
        counts_json=dict(path=str(counts_json), sha256=file_sha256(counts_json)),
        run_meta_json=dict(path=str(run_meta_json), sha256=file_sha256(run_meta_json)),
    )
    if eta_run_selection_used:
        inputs_dict["eta_run_selection_used"] = [
            dict(eta3=float(k), run=eta_run_selection_used[k]) for k in sorted(eta_run_selection_used.keys())
        ]

    return dict(
        figure_id="Fig6",
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        inputs=inputs_dict,
        analysis_config=asdict(cfg),
        layout=dict(
            figure_size_inches=list(fig_size_inches),
            grid=dict(rows=3, cols=2),
            eta_values=[float(x) for x in eta_values],
            profile_n=int(profile_n),
            signal_pair=list(signal_pair),
            control_pair=list(control_pair),
            style=dict(
                rcParams=style_rcparams if style_rcparams is not None else {},
                panel_colors=dict(panel_colors),
            ),
        ),
        outputs=dict(outputs),
        data=dict(
            panels=_panel_records(),
            notes=dict(
                kappa_eff_definition="kappa_eff = arg < exp(i * kappa_hat) >_contexts",
                required_settings=list(REQUIRED_SETTINGS),
            ),
        ),
    )
