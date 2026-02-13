# make_fig5.py
# CLI wrapper: takes TWO JSON inputs and produces Fig.5 + manifest + cached derived tables.

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fig5_data import Fig5AnalysisConfig, compute_fig5_products, build_fig5_manifest
from fig5_plot import plot_fig5, get_paper_style_manifest_rcparams, FIG5_ETA_SWEEP_COLORS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate UPDATED Fig.5 (Panels A,B only) from TWO JSON inputs: counts + run_meta."
    )
    p.add_argument("--counts", type=str, required=True, help="Path to combined counts JSON (seed_..._counts.json)")
    p.add_argument("--run-meta", type=str, required=True, help="Path to combined run_meta JSON (seed_..._run_meta.json)")
    p.add_argument("--out-dir", type=str, required=True, help="Output directory")
    p.add_argument("--boot-B", type=int, default=5000, help="Shot bootstrap replicates (default: 5000)")
    p.add_argument("--seed", type=int, default=12345, help="Base random seed (default: 12345)")
    p.add_argument("--ci-lo", type=float, default=0.025, help="Lower CI quantile (default: 0.025)")
    p.add_argument("--ci-hi", type=float, default=0.975, help="Upper CI quantile (default: 0.975)")
    p.add_argument("--amp-min-threshold", type=float, default=0.0, help="amp_min threshold (default: 0.0)")
    p.add_argument("--point-estimator", type=str, default="boot_median", choices=["trial", "boot_median", "boot_mean"],
                   help="Point estimator for V_circ in Panel A: trial (raw), boot_median (default), boot_mean")
    # Kept only for backward compatibility with older invocations.
    p.add_argument("--profile-eta3", type=float, default=0.2, help="[DEPRECATED] (unused) Old Panel C eta3")
    p.add_argument("--profile-n", type=int, default=7, help="[DEPRECATED] (unused) Old Panel C n")
    p.add_argument("--no-png", action="store_true", help="If set, do not write a PNG copy")
    p.add_argument("--fig-w", type=float, default=3.3, help="Figure width in inches (default: 3.3)")
    p.add_argument("--fig-h", type=float, default=4.4, help="Figure height in inches (default: 4.4)")
    p.add_argument("--eta-run", action="append", default=[], help="Repeatable mapping of eta3 to run: --eta-run eta:run (e.g., --eta-run 0:3 --eta-run 0.1:16). If provided, only the selected run is used for that eta3.")
    return p.parse_args()


def parse_eta_run_args(items: list[str]) -> dict[float, object]:
    """Parse --eta-run flags into a mapping eta3 -> run (int or str)."""
    out: dict[float, object] = {}
    for s in items:
        if ":" not in s:
            raise ValueError(f"Invalid --eta-run value: {s!r}. Expected format eta:run (e.g., 0.1:16).")
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
            raise ValueError(f"Duplicate --eta-run for eta3={eta_s!r}.")
        out[key] = run
    return out


def main() -> None:
    args = parse_args()
    counts_path = Path(args.counts)
    meta_path = Path(args.run_meta)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cfg = Fig5AnalysisConfig(
        boot_B=int(args.boot_B),
        seed=int(args.seed),
        ci_levels=(float(args.ci_lo), float(args.ci_hi)),
        amp_min_threshold=float(args.amp_min_threshold),
    
        point_estimator=str(args.point_estimator),
    )

    eta_run_selection = parse_eta_run_args(args.eta_run) if getattr(args, 'eta_run', None) else {}

    products = compute_fig5_products(
        counts_json=counts_path,
        run_meta_json=meta_path,
        cfg=cfg,
        eta_run_selection=eta_run_selection,
        profile_eta3=float(args.profile_eta3),
        profile_n=int(args.profile_n),
    )

    summary_df: pd.DataFrame = products["summary_df"]
    context_df: pd.DataFrame = products["context_df"]
    delta_df: pd.DataFrame = products["delta_df"]

    # Cache derived tables
    summary_csv = cache_dir / "fig5_summary.csv"
    context_csv = cache_dir / "fig5_context_level.csv"
    delta_csv = cache_dir / "fig5_deltaV.csv"

    summary_df.to_csv(summary_csv, index=False)
    context_df.to_csv(context_csv, index=False)
    delta_df.to_csv(delta_csv, index=False)

    # Render figure
    out_pdf = out_dir / "figure_5_qpu_AB.pdf"
    out_png = None if args.no_png else str(out_dir / "figure_5_qpu_AB.png")

    plot_fig5(
        summary_df=summary_df,
        context_df=context_df,
        out_pdf=str(out_pdf),
        out_png=out_png,
        fig_size_inches=(float(args.fig_w), float(args.fig_h)),
    )

    # Manifest JSON (machine-readable figure spec)
    outputs = {
        "figure_pdf": str(out_pdf),
        "figure_png": str(out_dir / "figure_5_qpu_AB.png") if out_png else None,
        "summary_csv": str(summary_csv),
        "context_csv": str(context_csv),
        "delta_csv": str(delta_csv),
    }
    manifest = build_fig5_manifest(
        counts_json=counts_path,
        run_meta_json=meta_path,
        cfg=cfg,
        summary_df=summary_df,
        outputs=outputs,
        eta_run_selection=eta_run_selection,
        style_rcparams=get_paper_style_manifest_rcparams(),
        sweep_palette=FIG5_ETA_SWEEP_COLORS,
    )

    manifest_path = out_dir / "figure_5_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"[OK] Wrote: {out_pdf}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()