# make_fig4_sim.py
# CLI wrapper: generate the SIMULATION analogue of Fig.6 (η3 sweep, 3x2 grid)
# from simulation artifacts.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fig4_sim_data import Fig6SimAnalysisConfig, compute_fig4_sim_products, build_fig4_sim_manifest
from fig4_sim_plot import plot_fig4_sim, get_paper_style_manifest_rcparams, FIG4_SIM_COLORS


def parse_pair_arg(s: str) -> tuple[int, int]:
    """Parse "i,j" into (i,j). Accepts "0,1" or "(0,1)"."""
    s = s.strip().strip("()")
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2:
        raise ValueError(f"Bad pair spec: {s!r} (expected 'i,j')")
    return (int(parts[0]), int(parts[1]))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate simulation Fig.6 (η3 sweep 3x2 grid) from simulation artifacts."
    )
    ap.add_argument("--trial-summary-csv", type=str, required=True, help="Path to combined trial summary CSV.")
    ap.add_argument("--rows-csv", type=str, required=True, help="Path to combined per-context rows CSV.")
    ap.add_argument("--run-meta-json", type=str, default=None, help="Optional run_meta JSON (for manifest).")
    ap.add_argument("--stats-meta-json", type=str, default=None, help="Optional stats_meta JSON (for manifest).")
    ap.add_argument("--out-dir", type=str, default=".", help="Output directory.")
    ap.add_argument("--png", action="store_true", help="Also save PNG.")

    # Figure knobs
    ap.add_argument("--n", type=int, default=7, help="Profile n (default: 7).")
    ap.add_argument("--eta-values", type=str, default="0,0.1,0.2", help="Comma-separated η3 values.")
    ap.add_argument("--signal-pair", type=str, default="0,1", help="Signal pair 'i,j' (default: 0,1).")
    ap.add_argument("--control-pair", type=str, default="2,3", help="Control pair 'i,j' (default: 2,3).")

    # Trial selection
    ap.add_argument(
        "--trial-policy",
        type=str,
        default="median_by_signal",
        choices=["median_by_signal", "fixed"],
        help="Representative trial selection policy.",
    )
    ap.add_argument("--trial-id", type=int, default=None, help="Only used if --trial-policy fixed.")
    ap.add_argument(
        "--trial-select-eta3",
        type=float,
        default=0.2,
        help="η3 used to select representative trial when --trial-policy median_by_signal (default: 0.2).",
    )

    # Quality filter
    ap.add_argument(
        "--amp-min-threshold",
        type=float,
        default=0.0,
        help="Optional amp_min threshold for κ_eff/V_circ computation (default: 0.0 = disabled).",
    )

    # Layout
    ap.add_argument("--fig-w", type=float, default=6.967, help="Figure width in inches.")
    ap.add_argument("--fig-h", type=float, default=6.27, help="Figure height in inches.")

    args = ap.parse_args()

    trial_summary_csv = Path(args.trial_summary_csv)
    rows_csv = Path(args.rows_csv)
    run_meta_json = Path(args.run_meta_json) if args.run_meta_json else None
    stats_meta_json = Path(args.stats_meta_json) if args.stats_meta_json else None

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    signal_pair = parse_pair_arg(args.signal_pair)
    control_pair = parse_pair_arg(args.control_pair)
    eta_values = tuple(float(x.strip()) for x in args.eta_values.split(",") if x.strip())
    if len(eta_values) != 3:
        raise ValueError("--eta-values must have exactly 3 comma-separated values (e.g., '0,0.1,0.2').")

    cfg = Fig6SimAnalysisConfig(
        trial_policy=str(args.trial_policy),
        trial_id=int(args.trial_id) if args.trial_id is not None else None,
        trial_select_eta3=float(args.trial_select_eta3),
        amp_min_threshold=float(args.amp_min_threshold),
    )

    products = compute_fig4_sim_products(
        trial_summary_csv=trial_summary_csv,
        rows_csv=rows_csv,
        cfg=cfg,
        eta_values=eta_values,  # type: ignore[arg-type]
        profile_n=int(args.n),
        signal_pair=signal_pair,
        control_pair=control_pair,
    )

    panel_df = products["panel_df"]
    panel_stats_df = products["panel_stats_df"]
    chosen_trial_id = int(products["chosen_trial_id"])

    # Cache extracted panel data
    cache_dir = out_dir / "fig4_sim_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    panel_csv_out = cache_dir / "fig4_sim_panel_df.csv"
    stats_csv_out = cache_dir / "fig4_sim_panel_stats_df.csv"
    panel_df.to_csv(panel_csv_out, index=False)
    panel_stats_df.to_csv(stats_csv_out, index=False)

    out_pdf = out_dir / "figure_4_sim_eta_sweep.pdf"
    out_png = (out_dir / "figure_4_sim_eta_sweep.png") if args.png else None

    plot_fig4_sim(
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        out_pdf=str(out_pdf),
        out_png=str(out_png) if out_png is not None else None,
        fig_size_inches=(float(args.fig_w), float(args.fig_h)),
        # title=rf"Simulation $n={int(args.n)}$ (trial_id={chosen_trial_id})",
    )

    manifest = build_fig4_sim_manifest(
        trial_summary_csv=trial_summary_csv,
        rows_csv=rows_csv,
        run_meta_json=run_meta_json,
        stats_meta_json=stats_meta_json,
        cfg=cfg,
        panel_df=panel_df,
        panel_stats_df=panel_stats_df,
        outputs=dict(
            figure_pdf=str(out_pdf),
            figure_png=str(out_png) if out_png is not None else None,
            panel_df_csv=str(panel_csv_out),
            panel_stats_df_csv=str(stats_csv_out),
        ),
        eta_values=eta_values,  # type: ignore[arg-type]
        profile_n=int(args.n),
        signal_pair=signal_pair,
        control_pair=control_pair,
        style_rcparams=get_paper_style_manifest_rcparams(),
        fig_size_inches=(float(args.fig_w), float(args.fig_h)),
        panel_colors={
            "signal": FIG4_SIM_COLORS["signal_kappa"],
            "control": FIG4_SIM_COLORS["control_kappa"],
            "amp": FIG4_SIM_COLORS["amp"],
        },
    )

    manifest_path = out_dir / "figure_4_sim_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[OK] chosen_trial_id={chosen_trial_id}")
    print(f"[OK] Wrote: {out_pdf}")
    if out_png is not None:
        print(f"[OK] Wrote: {out_png}")
    print(f"[OK] Wrote: {manifest_path}")
    print(f"[OK] Cache dir: {cache_dir}")


if __name__ == "__main__":
    main()
