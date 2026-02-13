# make_fig6.py
# CLI wrapper: takes TWO JSON inputs and produces Fig.6 + manifest + cached derived tables.

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from fig6_data import Fig6AnalysisConfig, compute_fig6_products, build_fig6_manifest
from fig6_plot import plot_fig6, get_paper_style_manifest_rcparams, FIG6_COLORS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Generate Fig.6 (3x2 kappa-profile grid with kappa_eff mean line) from TWO JSON inputs: counts + run_meta."
        )
    )
    p.add_argument("--counts", type=str, required=True, help="Path to combined counts JSON (seed_..._counts.json)")
    p.add_argument("--run-meta", type=str, required=True, help="Path to combined run_meta JSON (seed_..._meta.json)")
    p.add_argument("--out-dir", type=str, required=True, help="Output directory")
    p.add_argument("--profile-n", type=int, default=7, help="n used for the profiles (default: 7)")
    p.add_argument(
        "--eta-values",
        type=str,
        default="0,0.1,0.2",
        help="Comma-separated eta3 values for the rows (default: 0,0.1,0.2)",
    )
    p.add_argument("--signal-pair", type=str, default="0,1", help="Signal pair i,j (default: 0,1)")
    p.add_argument("--control-pair", type=str, default="1,4", help="Control pair i,j (default: 1,4)")
    p.add_argument("--amp-min-threshold", type=float, default=0.0, help="amp_min threshold for kappa_eff (default: 0.0)")
    p.add_argument("--no-png", action="store_true", help="If set, do not write a PNG copy")
    p.add_argument(
        "--eta-run",
        action="append",
        default=[],
        help=(
            "Repeatable mapping of eta3 to run: --eta-run eta:run (e.g., --eta-run 0:6 --eta-run 0.1:8). "
            "If omitted, we auto-select a single run per eta3 by max row-count."
        ),
    )
    return p.parse_args()


def _parse_pair(s: str) -> tuple[int, int]:
    parts = [x.strip() for x in s.split(",") if x.strip()]
    if len(parts) != 2:
        raise ValueError(f"Invalid pair spec: {s!r}. Expected 'i,j'.")
    return int(parts[0]), int(parts[1])


def _parse_eta_values(s: str) -> tuple[float, ...]:
    parts = [x.strip() for x in s.split(",") if x.strip()]
    if not parts:
        raise ValueError("--eta-values must contain at least one eta value")
    return tuple(float(x) for x in parts)


def parse_eta_run_args(items: list[str]) -> dict[float, object]:
    out: dict[float, object] = {}
    for s in items:
        if ":" not in s:
            raise ValueError(f"Invalid --eta-run value: {s!r}. Expected format eta:run (e.g., 0.1:8).")
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

    eta_values = _parse_eta_values(args.eta_values)
    signal_pair = _parse_pair(args.signal_pair)
    control_pair = _parse_pair(args.control_pair)

    cfg = Fig6AnalysisConfig(amp_min_threshold=float(args.amp_min_threshold))

    eta_run_selection = parse_eta_run_args(args.eta_run) if getattr(args, "eta_run", None) else {}

    products = compute_fig6_products(
        counts_json=counts_path,
        run_meta_json=meta_path,
        cfg=cfg,
        eta_values=tuple(float(x) for x in eta_values),
        profile_n=int(args.profile_n),
        signal_pair=signal_pair,
        control_pair=control_pair,
        eta_run_selection=eta_run_selection,
        auto_select_runs_if_missing=True,
    )

    panel_df: pd.DataFrame = products["panel_df"]
    panel_stats_df: pd.DataFrame = products["panel_stats_df"]
    eta_run_sel_used: dict[float, object] = products.get("eta_run_selection_used", {})

    # Cache derived tables
    panel_csv = cache_dir / "fig6_panel_context_level.csv"
    panel_stats_csv = cache_dir / "fig6_panel_stats.csv"
    panel_df.to_csv(panel_csv, index=False)
    panel_stats_df.to_csv(panel_stats_csv, index=False)

    # Render figure
    out_pdf = out_dir / "figure_6_scalar_vs_profile.pdf"
    out_png = None if args.no_png else str(out_dir / "figure_6_scalar_vs_profile.png")

    plot_fig6(
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        out_pdf=str(out_pdf),
        out_png=out_png,
    )

    outputs = {
        "figure_pdf": str(out_pdf),
        "figure_png": str(out_dir / "figure_6_scalar_vs_profile.png") if out_png else None,
        "panel_csv": str(panel_csv),
        "panel_stats_csv": str(panel_stats_csv),
    }

    manifest = build_fig6_manifest(
        counts_json=counts_path,
        run_meta_json=meta_path,
        cfg=cfg,
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        outputs=outputs,
        eta_values=tuple(float(x) for x in eta_values),
        profile_n=int(args.profile_n),
        signal_pair=signal_pair,
        control_pair=control_pair,
        eta_run_selection_used=eta_run_sel_used,
        style_rcparams=get_paper_style_manifest_rcparams(),
        fig_size_inches=(6.967, 6.27),
        panel_colors=FIG6_COLORS,
    )

    manifest_path = out_dir / "figure_6_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"[OK] Wrote: {out_pdf}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()