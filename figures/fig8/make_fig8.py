# make_fig8.py
# CLI wrapper to generate Appendix Fig. 8 (Day1 vs Day2 repeatability)
# from ONE combined counts JSON.

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fig8_data import Fig5AnalysisConfig, compute_fig8_day_products, build_fig8_manifest
from fig8_plot import plot_fig8, get_paper_style_manifest_rcparams


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate Appendix Fig. 9 (Day1 vs Day2 repeatability) from ONE combined counts JSON.\n"
            "You select which (eta3, run) belongs to Day1 and Day2 via repeatable CLI flags."
        )
    )
    p.add_argument("--counts", type=str, required=True, help="Path to combined counts JSON (seed_..._counts.json)")
    p.add_argument("--out-dir", type=str, required=True, help="Output directory")

    # Analysis knobs
    p.add_argument("--boot-B", type=int, default=5000, help="Shot bootstrap replicates (default: 5000)")
    p.add_argument("--seed", type=int, default=12345, help="Base random seed (default: 12345)")
    p.add_argument("--ci-lo", type=float, default=0.025, help="Lower CI quantile (default: 0.025)")
    p.add_argument("--ci-hi", type=float, default=0.975, help="Upper CI quantile (default: 0.975)")
    p.add_argument("--amp-min-threshold", type=float, default=0.0, help="amp_min threshold (default: 0.0)")
    p.add_argument(
        "--point-estimator",
        type=str,
        default="boot_median",
        choices=["trial", "boot_median", "boot_mean"],
        help="Point estimator for V_circ: trial (raw), boot_median (default), boot_mean",
    )

    # Fig.9 design knobs
    p.add_argument("--n", type=int, default=7, help="Key n to compare (default: 7)")
    p.add_argument(
        "--metric-mode",
        type=str,
        default="delta",
        choices=["delta", "V"],
        help="Panel A metric: delta (ΔV_circ) or V (plot V_circ for signal+control)",
    )
    p.add_argument("--signal-pair", type=str, default="0,1", help="Signal pair i,j (default: 0,1)")
    p.add_argument("--control-pair", type=str, default="1,4", help="Control pair i,j (default: 1,4)")
    p.add_argument(
        "--no-control-amp",
        action="store_true",
        help="If set, Panel B shows amp_min only for the signal pair",
    )
    p.add_argument("--no-png", action="store_true", help="If set, do not write a PNG copy")

    # Day selections (repeatable flags)
    p.add_argument(
        "--day1-eta-run",
        action="append",
        default=[],
        help=(
            "Repeatable mapping for Day1: --day1-eta-run eta:run (e.g., --day1-eta-run 0:6 --day1-eta-run 0.2:5). "
            "Each provided eta3 is filtered to that run."
        ),
    )
    p.add_argument(
        "--day2-eta-run",
        action="append",
        default=[],
        help=(
            "Repeatable mapping for Day2: --day2-eta-run eta:run (e.g., --day2-eta-run 0:8 --day2-eta-run 0.2:7). "
            "Each provided eta3 is filtered to that run."
        ),
    )
    return p.parse_args()


def _parse_pair(s: str) -> tuple[int, int]:
    parts = [x.strip() for x in str(s).split(",")]
    if len(parts) != 2:
        raise ValueError(f"Invalid pair string {s!r}. Expected format 'i,j' (e.g., '0,1').")
    return int(parts[0]), int(parts[1])


def parse_eta_run_args(items: list[str]) -> dict[float, object]:
    """Parse repeatable --day*-eta-run flags into a mapping eta3 -> run."""
    out: dict[float, object] = {}
    for s in items:
        if ":" not in s:
            raise ValueError(f"Invalid eta-run value: {s!r}. Expected format eta:run (e.g., 0.1:16).")
        eta_s, run_s = s.split(":", 1)
        eta = float(eta_s)
        run_s = run_s.strip()
        run: object
        if run_s.lstrip("-").isdigit():
            run = int(run_s)
        else:
            run = run_s
        key = round(float(eta), 12)
        if key in out:
            raise ValueError(f"Duplicate eta mapping for eta3={eta_s!r}.")
        out[key] = run
    return out


def main() -> None:
    args = parse_args()

    counts_path = Path(args.counts)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    signal_pair = _parse_pair(args.signal_pair)
    control_pair = _parse_pair(args.control_pair)
    include_control_amp = not bool(args.no_control_amp)

    day1_sel = parse_eta_run_args(args.day1_eta_run)
    day2_sel = parse_eta_run_args(args.day2_eta_run)
    if not day1_sel or not day2_sel:
        raise ValueError("Both --day1-eta-run and --day2-eta-run must be provided (at least one mapping each).")

    cfg = Fig5AnalysisConfig(
        boot_B=int(args.boot_B),
        seed=int(args.seed),
        ci_levels=(float(args.ci_lo), float(args.ci_hi)),
        amp_min_threshold=float(args.amp_min_threshold),
        point_estimator=str(args.point_estimator),
    )

    # Compute day-specific products
    day1 = compute_fig8_day_products(
        counts_json=counts_path,
        cfg=cfg,
        eta_run_selection=day1_sel,
        signal_pair=signal_pair,
        control_pair=control_pair,
        keep_only_selected_etas=True,
    )
    day2 = compute_fig8_day_products(
        counts_json=counts_path,
        cfg=cfg,
        eta_run_selection=day2_sel,
        signal_pair=signal_pair,
        control_pair=control_pair,
        keep_only_selected_etas=True,
    )

    day1_summary: pd.DataFrame = day1["summary_df"]
    day2_summary: pd.DataFrame = day2["summary_df"]
    day1_delta: pd.DataFrame = day1["delta_df"]
    day2_delta: pd.DataFrame = day2["delta_df"]

    # Cache derived tables (audit trail)
    (cache_dir / "fig8_day1_summary.csv").write_text(day1_summary.to_csv(index=False))
    (cache_dir / "fig8_day2_summary.csv").write_text(day2_summary.to_csv(index=False))
    (cache_dir / "fig8_day1_deltaV.csv").write_text(day1_delta.to_csv(index=False))
    (cache_dir / "fig8_day2_deltaV.csv").write_text(day2_delta.to_csv(index=False))

    # Render
    out_pdf = out_dir / "figure_8_repeatability.pdf"
    out_png = None if args.no_png else str(out_dir / "figure_8_repeatability.png")

    plot_fig8(
        day1_summary_df=day1_summary,
        day2_summary_df=day2_summary,
        day1_delta_df=day1_delta,
        day2_delta_df=day2_delta,
        out_pdf=str(out_pdf),
        out_png=out_png,
        n_key=int(args.n),
        metric_mode=str(args.metric_mode),
        signal_pair=signal_pair,
        control_pair=control_pair,
        include_control_amp=include_control_amp,
    )

    outputs = {
        "figure_pdf": str(out_pdf),
        "figure_png": str(out_dir / "figure_8_repeatability.png") if out_png else None,
        "day1_summary_csv": str(cache_dir / "fig8_day1_summary.csv"),
        "day2_summary_csv": str(cache_dir / "fig8_day2_summary.csv"),
        "day1_delta_csv": str(cache_dir / "fig8_day1_deltaV.csv"),
        "day2_delta_csv": str(cache_dir / "fig8_day2_deltaV.csv"),
    }

    manifest = build_fig8_manifest(
        counts_json=counts_path,
        cfg=cfg,
        day1_selection=day1_sel,
        day2_selection=day2_sel,
        n_key=int(args.n),
        metric_mode=str(args.metric_mode),
        signal_pair=signal_pair,
        control_pair=control_pair,
        outputs=outputs,
        style_rcparams=get_paper_style_manifest_rcparams(),
    )

    manifest_path = out_dir / "figure_8_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"[OK] Wrote: {out_pdf}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()
