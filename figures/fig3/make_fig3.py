# make_fig3.py
# CLI wrapper: takes 4 simulation artifacts (2 CSV + 2 JSON) and produces Fig.3 + manifest + cached derived tables.

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fig3_data import Fig3AnalysisConfig, compute_fig3_products, build_fig3_manifest
from fig3_plot import plot_fig3, get_paper_style_manifest_rcparams


def parse_pair_arg(s: str) -> tuple[int, int]:
    s = s.strip()
    if "," not in s:
        raise argparse.ArgumentTypeError("pair must be formatted like '0,1'")
    a, b = s.split(",", 1)
    return int(a), int(b)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate Fig.3 (Simulation scaling report) from 4 artifacts: trial_summary.csv + rows.csv + run_meta.json + stats_meta.json."
    )
    p.add_argument("--trial-summary", type=str, required=True, help="Path to trial_summary CSV (grid_..._trial_summary.csv)")
    p.add_argument("--rows", type=str, required=True, help="Path to rows CSV (grid_..._rows.csv)")
    p.add_argument("--run-meta", type=str, required=True, help="Path to run_meta JSON (grid_..._run_meta.json)")
    p.add_argument("--stats-meta", type=str, required=True, help="Path to stats_meta JSON (grid_..._stats_meta.json)")
    p.add_argument("--out-dir", type=str, required=True, help="Output directory")
    p.add_argument("--boot-B", type=int, default=5000, help="Trial bootstrap replicates (default: 5000)")
    p.add_argument("--seed", type=int, default=12345, help="Base random seed (default: 12345)")
    p.add_argument("--ci-lo", type=float, default=0.025, help="Lower CI quantile (default: 0.025)")
    p.add_argument("--ci-hi", type=float, default=0.975, help="Upper CI quantile (default: 0.975)")
    p.add_argument(
        "--point-estimator",
        type=str,
        default="boot_median",
        choices=["trial", "boot_median", "boot_mean"],
        help="Point estimator for V_circ: trial (sample mean), boot_median (default), boot_mean",
    )
    p.add_argument("--signal-pair", type=parse_pair_arg, default=(0, 1), help="Signal pair i,j (default: 0,1)")
    p.add_argument("--control-pair", type=parse_pair_arg, default=(2, 3), help="Control pair i,j (default: 2,3)")
    p.add_argument("--fig-w", type=float, default=3.3, help="Figure width in inches (default: 3.3)")
    p.add_argument("--fig-h", type=float, default=4.4, help="Figure height in inches (default: 4.4)")
    p.add_argument("--no-png", action="store_true", help="If set, do not write a PNG copy")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    trial_summary_csv = Path(args.trial_summary)
    rows_csv = Path(args.rows)
    run_meta_json = Path(args.run_meta)
    stats_meta_json = Path(args.stats_meta)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cfg = Fig3AnalysisConfig(
        boot_B=int(args.boot_B),
        seed=int(args.seed),
        ci_levels=(float(args.ci_lo), float(args.ci_hi)),
        point_estimator=str(args.point_estimator),
    )

    signal_pair = tuple(args.signal_pair)
    control_pair = tuple(args.control_pair)

    products = compute_fig3_products(
        trial_summary_csv=trial_summary_csv,
        rows_csv=rows_csv,
        run_meta_json=run_meta_json,
        stats_meta_json=stats_meta_json,
        cfg=cfg,
        signal_pair=signal_pair,
        control_pair=control_pair,
    )
    summary_df: pd.DataFrame = products["summary_df"]
    delta_df: pd.DataFrame = products["delta_df"]

    # Cache derived tables (so you can iterate on plotting quickly)
    summary_csv_out = cache_dir / "fig3_summary.csv"
    delta_csv_out = cache_dir / "fig3_deltaV.csv"
    summary_df.to_csv(summary_csv_out, index=False)
    delta_df.to_csv(delta_csv_out, index=False)

    out_pdf = out_dir / "figure_3_sim_scaling.pdf"
    out_png = None if args.no_png else (out_dir / "figure_3_sim_scaling.png")

    plot_fig3(
        summary_df=summary_df,
        out_pdf=str(out_pdf),
        out_png=str(out_png) if out_png is not None else None,
        fig_size_inches=(float(args.fig_w), float(args.fig_h)),
        signal_pair=signal_pair,
        control_pair=control_pair,
    )

    manifest = build_fig3_manifest(
        trial_summary_csv=trial_summary_csv,
        rows_csv=rows_csv,
        run_meta_json=run_meta_json,
        stats_meta_json=stats_meta_json,
        cfg=cfg,
        summary_df=summary_df,
        outputs=dict(
            figure_pdf=str(out_pdf),
            figure_png=str(out_png) if out_png is not None else None,
            summary_csv=str(summary_csv_out),
            delta_csv=str(delta_csv_out),
        ),
        style_rcparams=get_paper_style_manifest_rcparams(),
        fig_size_inches=(float(args.fig_w), float(args.fig_h)),
        signal_pair=signal_pair,
        control_pair=control_pair,
    )

    manifest_path = out_dir / "figure_3_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[OK] Wrote: {out_pdf}")
    if out_png is not None:
        print(f"[OK] Wrote: {out_png}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()