# make_fig7.py
# CLI wrapper: takes FOUR JSON inputs and produces Appendix Fig.7
# plus cached derived tables + a minimal manifest.

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fig7_data import fig7AnalysisConfig, compute_fig7_products, build_fig7_manifest
from fig7_plot import plot_fig7, get_paper_style_manifest_rcparams


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate Appendix Fig.8 (schedule/drift ablation: blocked vs interleaved) "
            "from FOUR JSON inputs (counts + run_meta for each schedule)."
        )
    )

    p.add_argument("--interleave-counts", type=str, required=True, help="Path to interleave counts JSON (list of segments; counts.v2 payloads)")
    p.add_argument("--interleave-meta", type=str, required=True, help="Path to interleave run_meta JSON (list of segments)")
    p.add_argument("--block-counts", type=str, required=True, help="Path to blocked counts JSON (single counts.v2 payload)")
    p.add_argument("--block-meta", type=str, required=True, help="Path to blocked run_meta JSON (single payload)")
    p.add_argument("--outdir", "--out-dir", dest="out_dir", type=str, required=True, help="Output directory")
    p.add_argument("--tag", type=str, default="", help="Optional tag appended to output filenames")
    p.add_argument("--no-png", action="store_true", help="If set, do not write a PNG copy")

    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.tag:
        args.tag = f"_{args.tag}"

    interleave_counts = Path(args.interleave_counts)
    interleave_meta = Path(args.interleave_meta)
    block_counts = Path(args.block_counts)
    block_meta = Path(args.block_meta)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cfg = fig7AnalysisConfig()

    products = compute_fig7_products(
        interleave_counts_json=interleave_counts,
        interleave_meta_json=interleave_meta,
        block_counts_json=block_counts,
        block_meta_json=block_meta,
        cfg=cfg,
    )

    ctx_df: pd.DataFrame = products["context_df"]
    sum_df: pd.DataFrame = products["summary_df"]
    run_order: list[str] = products["run_order"]

    # Derived tables (CSV)
    # - cache/ : matches Fig.5 conventions
    # - outdir/: backwards compatible with the original monolithic fig_7_make.py
    ctx_csv = cache_dir / f"derived_context_kappa{args.tag}.csv"
    sum_csv = cache_dir / f"summary_metrics{args.tag}.csv"
    ctx_csv_root = out_dir / f"derived_context_kappa{args.tag}.csv"
    sum_csv_root = out_dir / f"summary_metrics{args.tag}.csv"

    ctx_df.to_csv(ctx_csv, index=False)
    sum_df.to_csv(sum_csv, index=False)
    ctx_df.to_csv(ctx_csv_root, index=False)
    sum_df.to_csv(sum_csv_root, index=False)

    # Render figure
    out_pdf = out_dir / f"Fig_7{args.tag}.pdf"
    out_png = None if args.no_png else str(out_dir / f"Fig_7{args.tag}.png")
    # title = f"Fig.8 | schedule ablation (blocked vs interleaved)"

    plot_fig7(
        summary_df=sum_df,
        run_order=run_order,
        out_pdf=str(out_pdf),
        out_png=out_png,
        # title=title,
    )

    # Manifest JSON (machine-readable spec)
    outputs = {
        "figure_pdf": str(out_pdf),
        "figure_png": str(out_png) if out_png else None,
        "context_csv": str(ctx_csv),
        "summary_csv": str(sum_csv),
        "context_csv_root": str(ctx_csv_root),
        "summary_csv_root": str(sum_csv_root),
    }
    manifest = build_fig7_manifest(
        interleave_counts_json=interleave_counts,
        interleave_meta_json=interleave_meta,
        block_counts_json=block_counts,
        block_meta_json=block_meta,
        cfg=cfg,
        outputs=outputs,
        style_rcparams=get_paper_style_manifest_rcparams(),
    )
    manifest_path = out_dir / f"figure_7{args.tag}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"[OK] Wrote: {out_pdf}")
    if out_png:
        print(f"[OK] Wrote: {out_png}")
    print(f"[OK] Wrote: {ctx_csv}")
    print(f"[OK] Wrote: {sum_csv}")
    print(f"[OK] Wrote: {ctx_csv_root}")
    print(f"[OK] Wrote: {sum_csv_root}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()
