"""stats.py

Module 3: Statistics / Trial Summary

Reads sim_runner output (rows.csv + run_meta.json),
aggregates over contexts to produce trial-level summary.

Input:
    runs/{run_id}/
    ├── rows.csv         (1 row = pair, context, trial)
    └── run_meta.json

Output:
    runs/{run_id}/
    ├── trial_summary.csv   (1 row = pair, trial)
    └── stats_meta.json
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

# Try pandas, fall back to manual CSV
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

"""Note: Parquet is intentionally not required. We prefer rows.csv."""


# =============================================================================
# Constants
# =============================================================================

STATS_VERSION = "stats.v1"


# =============================================================================
# Exceptions
# =============================================================================

class StatsError(Exception):
    """Statistics processing error."""
    pass


# =============================================================================
# Circular statistics (self-contained)
# =============================================================================

def circular_mean_and_R(kappa_rad: np.ndarray) -> tuple[float, float]:
    """Compute circular mean and resultant length R.
    
    Args:
        kappa_rad: 1D array of angles (radians)
    
    Returns:
        (mean_angle, R) where R = |mean(exp(i*kappa))|
    """
    if kappa_rad.size == 0:
        return float("nan"), float("nan")
    
    # Filter non-finite
    valid = kappa_rad[np.isfinite(kappa_rad)]
    if valid.size == 0:
        return float("nan"), float("nan")
    
    # Phasor mean
    z = np.exp(1j * valid)
    mean_z = np.mean(z)
    
    R = float(np.abs(mean_z))
    mean_angle = float(np.angle(mean_z))
    
    return mean_angle, R


def circular_variance_from_R(R: float) -> float:
    """Circular variance = 1 - R."""
    if not math.isfinite(R):
        return float("nan")
    return 1.0 - R


# =============================================================================
# Data loading
# =============================================================================

def load_rows(run_dir: Path, rows_file: Optional[str] = None) -> "pd.DataFrame":
    """Load rows as DataFrame.

    Preferred input is CSV (rows.csv). Parquet is treated as a legacy fallback.
    """
    if not HAS_PANDAS:
        raise StatsError("pandas is required for stats module")
    
    # 1) Use explicit rows_file from run_meta.json if available
    candidates: List[Path] = []
    if rows_file:
        candidates.append(run_dir / rows_file)

    # 2) Conventional names (CSV first)
    candidates.append(run_dir / "rows.csv")
    candidates.append(run_dir / "rows.parquet")

    for p in candidates:
        if not p.exists():
            continue

        if p.suffix.lower() == ".csv":
            return pd.read_csv(p)

        if p.suffix.lower() == ".parquet":
            # Legacy fallback: attempt via pandas (requires pyarrow/fastparquet).
            try:
                return pd.read_parquet(p)
            except Exception as e:
                raise StatsError(
                    f"Found legacy parquet rows file ({p.name!r}), but a parquet engine is not available. "
                    "Rerun Module 2 to generate rows.csv (recommended), or install pyarrow/fastparquet."
                ) from e

        raise StatsError(f"Unsupported rows file extension: {p.suffix!r} (expected .csv)")

    raise StatsError(f"No rows file found in {run_dir} (tried meta-specified file, rows.csv, rows.parquet)")


def load_meta(run_dir: Path) -> Dict[str, Any]:
    """Load run_meta.json."""
    meta_path = run_dir / "run_meta.json"
    if not meta_path.exists():
        raise StatsError(f"run_meta.json not found in {run_dir}")
    
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# Core computation
# =============================================================================

def compute_trial_summary(
    df: "pd.DataFrame",
    run_id: str,
    shots_per_setting: Optional[int] = None,
) -> "pd.DataFrame":
    """Compute trial-level summary by aggregating over contexts.
    
    Input: DataFrame with columns [n, i, j, z_rest_int, trial_id, kappa_hat, amp_a, amp_b, ...]
    Output: DataFrame with 1 row per (n, i, j, trial_id)
    """
    
    results: List[Dict[str, Any]] = []
    
    # Group by (n, i, j, trial_id)
    grouped = df.groupby(["n", "i", "j", "trial_id"])
    
    for (n, i, j, trial_id), group in grouped:
        kappa_hat = group["kappa_hat"].values
        amp_a = group["amp_a"].values
        amp_b = group["amp_b"].values
        
        num_contexts = len(group)
        
        # 1. Circular variance over contexts
        mean_angle, R = circular_mean_and_R(kappa_hat)
        circ_var = circular_variance_from_R(R)
        
        # 2. Amplitude quality metrics
        amp_min = np.minimum(amp_a, amp_b)  # element-wise min
        amp_min_valid = amp_min[np.isfinite(amp_min)]
        
        if amp_min_valid.size > 0:
            amp_min_mean = float(np.mean(amp_min_valid))
            amp_min_q10 = float(np.quantile(amp_min_valid, 0.1))
        else:
            amp_min_mean = float("nan")
            amp_min_q10 = float("nan")
        
        row = {
            "run_id": run_id,
            "n": int(n),
            "i": int(i),
            "j": int(j),
            "trial_id": int(trial_id),
            "num_contexts": num_contexts,
            "kappa_ctx_R_trial": R,
            "kappa_ctx_circ_var_trial": circ_var,
            "kappa_ctx_circ_mean_trial": mean_angle,
            "amp_min_mean_ctx_trial": amp_min_mean,
            "amp_min_q10_ctx_trial": amp_min_q10,
        }
        
        if shots_per_setting is not None:
            row["shots_per_setting"] = shots_per_setting
        
        results.append(row)
    
    return pd.DataFrame(results)


# =============================================================================
# I/O
# =============================================================================

def save_trial_summary(summary_df: "pd.DataFrame", output_path: Path) -> None:
    """Save trial summary to CSV."""
    summary_df.to_csv(output_path, index=False)


def save_stats_meta(
    run_dir: Path,
    output_path: Path,
    input_rows_file: str,
    input_meta_file: str,
    output_summary_file: str,
) -> None:
    """Save stats metadata."""
    meta = {
        "stats_version": STATS_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_run_dir": str(run_dir),
        "input_rows_file": input_rows_file,
        "input_run_meta_file": input_meta_file,
        "output_trial_summary_file": output_summary_file,
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


# =============================================================================
# Main entry point
# =============================================================================

def process_run(
    run_dir: Union[str, Path],
    output_summary_file: str = "trial_summary.csv",
    output_meta_file: str = "stats_meta.json",
) -> Path:
    """Process a single run directory and generate trial summary.
    
    Args:
        run_dir: path to run directory (contains rows.csv and run_meta.json)
        output_summary_file: filename for trial summary output
        output_meta_file: filename for stats metadata output
    
    Returns:
        Path to output summary file
    """
    run_dir = Path(run_dir)
    
    if not run_dir.exists():
        raise StatsError(f"Run directory not found: {run_dir}")
    
    # Load inputs
    meta = load_meta(run_dir)
    rows_file = (
        meta.get("output", {}).get("rows_file_effective")
        or meta.get("output", {}).get("rows_file")
        or None
    )
    df = load_rows(run_dir, rows_file=rows_file)
    
    run_id = meta.get("run_id", run_dir.name)
    shots_per_setting = meta.get("config", {}).get("shot", {}).get("shots")
    
    # Determine input filenames (for stats_meta)
    if rows_file and (run_dir / rows_file).exists():
        input_rows_file = rows_file
    elif (run_dir / "rows.csv").exists():
        input_rows_file = "rows.csv"
    elif (run_dir / "rows.parquet").exists():
        input_rows_file = "rows.parquet"
    else:
        input_rows_file = "(missing)"
    
    # Compute summary
    summary_df = compute_trial_summary(df, run_id, shots_per_setting)
    
    # Save outputs
    summary_path = run_dir / output_summary_file
    meta_path = run_dir / output_meta_file
    
    save_trial_summary(summary_df, summary_path)
    save_stats_meta(
        run_dir=run_dir,
        output_path=meta_path,
        input_rows_file=input_rows_file,
        input_meta_file="run_meta.json",
        output_summary_file=output_summary_file,
    )
    
    return summary_path


# =============================================================================
# CLI entry point
# =============================================================================

def main():
    """Command-line entry point."""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Compute trial summary statistics")
    parser.add_argument("run_dir", help="Path to run directory")
    parser.add_argument("--output", default="trial_summary.csv", help="Output filename")
    args = parser.parse_args()
    
    try:
        summary_path = process_run(args.run_dir, output_summary_file=args.output)
        print(f"Done. Output: {summary_path}")
    except StatsError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()