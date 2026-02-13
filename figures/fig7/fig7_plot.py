# fig7_plot.py
#
# Appendix Fig: Drift / schedule ablation (blocked vs interleaved settings)
#
# Plot stage only. Expects the summary_df produced by fig7_data.py.
#
# Alignment with Fig.5 visual philosophy:
#   - point = bootstrap median/mean (if provided in *_point columns)
#   - CI displayed as [ci_lo, ci_hi] whiskers via asymmetric error bars
#   - blocked segment highlighted with shading (less ambiguous than a single "Config Change" line)

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MultipleLocator


# -----------------------------------------------------------------------------
# Fig.5-matched editorial style
# -----------------------------------------------------------------------------

PAPER_STYLE_RCPARAMS: Dict[str, Any] = {
    "figure.dpi": 300,
    "font.family": "serif",
    "font.serif": ["CMU Serif", "Computer Modern", "DejaVu Serif"],
    "mathtext.fontset": "cm",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.grid": True,
    "grid.alpha": 0.15,
    "grid.linewidth": 0.5,
    "grid.linestyle": "-",
    "lines.linewidth": 1.2,
    "lines.markersize": 3.5,
}

COLOR_PALETTE = [
    "#548c8d",  # Petrol Cyan
    "#c2a855",  # Antique Gold
]

# ---------------------------------------------------------------------------
# Journal column width.  With constrained_layout + bbox_inches="tight"
# (pad_inches=0.1, the matplotlib default), the tight-cropped PDF width is
# figsize_width_in * 72 + 8.4 pt.  Setting figsize width so that this
# expression equals 246 pt gives every figure the exact same column width
# and, crucially, the same scale factor — so font sizes are identical.
# ---------------------------------------------------------------------------
_JOURNAL_COL_WIDTH_PT: float = 246.0
_TIGHT_OFFSET_PT: float = 8.4  # empirical: tight_w = figsize_w*72 + 8.4
_FIGSIZE_WIDTH_IN: float = (_JOURNAL_COL_WIDTH_PT - _TIGHT_OFFSET_PT) / 72.0  # 3.300 in


def get_paper_style_rcparams() -> Dict[str, Any]:
    return dict(PAPER_STYLE_RCPARAMS)


def get_paper_style_manifest_rcparams() -> Dict[str, Any]:
    """Return rcParams in a JSON-friendly schema (dot -> underscore)."""
    return {k.replace(".", "_"): v for k, v in PAPER_STYLE_RCPARAMS.items()}


def apply_paper_style() -> None:
    plt.rcParams.update(get_paper_style_rcparams())


# -----------------------------------------------------------------------------
# Tick formatter: wrap all tick labels in mathtext
# -----------------------------------------------------------------------------
def mathtext_formatter(x, pos):
    """Format tick labels as mathtext for font consistency."""
    if x == int(x):
        return rf"${int(x)}$"
    else:
        return rf"${x:g}$"


# -----------------------------------------------------------------------------
# Main figure
# -----------------------------------------------------------------------------


def plot_fig7(
    *,
    summary_df: pd.DataFrame,
    run_order: List[str],
    out_pdf: str,
    out_png: Optional[str] = None,
    title: Optional[str] = None,
    fig_size_inches: Tuple[float, float] = (_FIGSIZE_WIDTH_IN, 4.3),
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
) -> None:
    """Render Fig (2 stacked panels)."""

    apply_paper_style()

    if summary_df.empty:
        raise ValueError("plot_fig7: summary_df is empty")
    if not run_order:
        raise ValueError("plot_fig7: run_order is empty")

    required_cols = {"run_label", "pair", "shots_per_circuit", "V_circ", "amp_min_q10"}
    missing = sorted(required_cols - set(summary_df.columns))
    if missing:
        raise ValueError(f"plot_fig7: summary_df missing required columns: {missing}")

    pairs = sorted(summary_df["pair"].unique())

    # Prefer *_point columns if present (Fig.5-aligned plotting philosophy)
    V_col = "V_circ_point" if "V_circ_point" in summary_df.columns else "V_circ"
    A_col = "amp_min_q10_point" if "amp_min_q10_point" in summary_df.columns else "amp_min_q10"

    has_V_ci = {"V_circ_ci95_lo", "V_circ_ci95_hi"}.issubset(summary_df.columns)
    has_A_ci = {"amp_min_q10_ci95_lo", "amp_min_q10_ci95_hi"}.issubset(summary_df.columns)

    def _pivot(metric: str) -> pd.DataFrame:
        piv = summary_df.pivot(index="run_label", columns="pair", values=metric).reindex(run_order)
        for p in pairs:
            if p not in piv.columns:
                piv[p] = np.nan
        return piv

    piv_V = _pivot(V_col)
    piv_A = _pivot(A_col)

    piv_V_lo = _pivot("V_circ_ci95_lo") if has_V_ci else None
    piv_V_hi = _pivot("V_circ_ci95_hi") if has_V_ci else None
    piv_A_lo = _pivot("amp_min_q10_ci95_lo") if has_A_ci else None
    piv_A_hi = _pivot("amp_min_q10_ci95_hi") if has_A_ci else None

    shots_map = (
        summary_df.drop_duplicates(subset=["run_label"]).set_index("run_label")["shots_per_circuit"].to_dict()
    )

    xticks = np.arange(len(run_order))

    def format_label(l: str) -> str:
        if l == "I_sum":
            return r"I\,(\mathrm{sum})"
        return l

    # xticklabels - run name with shots in parentheses, single line
    xticklabels = [
        rf"${format_label(lbl)}\ ({shots_map.get(lbl, '')})$"
        for lbl in run_order
    ]

    fig = plt.figure(figsize=fig_size_inches, constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.1)
    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[1, 0], sharex=ax0)

    # Panel labels - mathtext
    for ax, label in zip([ax0, ax1], [r"$\mathbf{(A)}$", r"$\mathbf{(B)}$"]):
        ax.text(-0.02, 1.05, label, transform=ax.transAxes, fontsize=12, va="bottom", ha="right")

    # Pair styles matched to fig3_plot - all mathtext
    pair_styles = {
        f"({signal_pair[0]},{signal_pair[1]})": dict(
            marker="o", linestyle="-", markerfacecolor=None,
            label=rf"$\mathrm{{Signal}}\ ({signal_pair[0]},{signal_pair[1]})$", zorder=10
        ),
        f"({control_pair[0]},{control_pair[1]})": dict(
            marker="s", linestyle="--", markerfacecolor="white",
            label=rf"$\mathrm{{Control}}\ ({control_pair[0]},{control_pair[1]})$", zorder=9
        ),
    }

    for k, pair in enumerate(pairs):
        color = COLOR_PALETTE[k % len(COLOR_PALETTE)]
        sty = pair_styles.get(pair, dict(marker="o", linestyle="-", markerfacecolor=None, label=rf"$\mathrm{{Pair}}\ {pair}$", zorder=10))

        # Panel A: V_circ
        yV = piv_V[pair].to_numpy(dtype=float)
        mfc = color if sty["markerfacecolor"] is None else sty["markerfacecolor"]
        if has_V_ci and piv_V_lo is not None and piv_V_hi is not None:
            lo = piv_V_lo[pair].to_numpy(dtype=float)
            hi = piv_V_hi[pair].to_numpy(dtype=float)
            yerr = np.vstack([
                np.clip(yV - lo, 0.0, np.inf),
                np.clip(hi - yV, 0.0, np.inf),
            ])
            ax0.errorbar(
                xticks,
                yV,
                yerr=yerr,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                color=color,
                markerfacecolor=mfc,
                markeredgecolor=color,
                markeredgewidth=1.2,
                linewidth=1.5,
                capsize=2.5,
                label=sty["label"],
                zorder=sty["zorder"],
            )
        else:
            ax0.plot(
                xticks,
                yV,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                color=color,
                markerfacecolor=mfc,
                markeredgecolor=color,
                markeredgewidth=1.2,
                linewidth=1.5,
                label=sty["label"],
                zorder=sty["zorder"],
            )

        # Panel B: q10(amp_min)
        yA = piv_A[pair].to_numpy(dtype=float)
        if has_A_ci and piv_A_lo is not None and piv_A_hi is not None:
            lo = piv_A_lo[pair].to_numpy(dtype=float)
            hi = piv_A_hi[pair].to_numpy(dtype=float)
            yerr = np.vstack([
                np.clip(yA - lo, 0.0, np.inf),
                np.clip(hi - yA, 0.0, np.inf),
            ])
            ax1.errorbar(
                xticks,
                yA,
                yerr=yerr,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                color=color,
                markerfacecolor=mfc,
                markeredgecolor=color,
                markeredgewidth=1.2,
                linewidth=1.5,
                capsize=2.5,
                zorder=sty["zorder"],
            )
        else:
            ax1.plot(
                xticks,
                yA,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                color=color,
                markerfacecolor=mfc,
                markeredgecolor=color,
                markeredgewidth=1.2,
                linewidth=1.5,
                zorder=sty["zorder"],
            )

    # Labels - all mathtext
    ax0.set_ylabel(r"$V_{\mathrm{circ}}$")
    ax0.tick_params(labelbottom=False)
    ax1.set_ylabel(r"$\mathrm{amp}_{\min}$")
    ax1.set_xticks(xticks)
    ax1.set_xticklabels(xticklabels, rotation=45, ha="right")
    ax1.set_ylim(0.0, 1.1)

    # Apply mathtext formatter to y-axes
    ax0.yaxis.set_major_locator(MultipleLocator(0.001))
    ax0.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))
    ax1.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))

    # Highlight blocked segment (B) with shading + boundary markers
    if "B" in run_order:
        b_idx = run_order.index("B")
        left, right = b_idx - 0.55, b_idx + 0.55
        for ax in [ax0, ax1]:
            ax.axvspan(left, right, color="gray", alpha=0.12, zorder=0)
            ax.axvline(left, linestyle=":", color="gray", linewidth=1.2, alpha=0.6, zorder=1)
            ax.axvline(right, linestyle=":", color="gray", linewidth=1.2, alpha=0.6, zorder=1)

        # "Blocked" label inside shading, top of panel (A)
        ax0.text(
            b_idx, ax0.get_ylim()[1] * 0.95,
            r"$\mathrm{Blocked}$",
            ha="center", va="top",
            fontsize=8,
            color="gray",
        )

    if title:
        fig.suptitle(rf"$\mathrm{{{title.replace(' ', r'\ ')}}}$", fontsize=10, y=1.02)

    # Legend inside panel (B) — data lives near y=0.85–1.0, so lower-right is clear
    pair_handles = [
        Line2D([0], [0], color=COLOR_PALETTE[0], marker="o", linestyle="-", markersize=3.5,
               label=rf"$\mathrm{{Signal}}\ ({signal_pair[0]},{signal_pair[1]})$"),
        Line2D([0], [0], color=COLOR_PALETTE[1], marker="s", linestyle="--", markerfacecolor="white", markersize=3.5,
               label=rf"$\mathrm{{Control}}\ ({control_pair[0]},{control_pair[1]})$"),
    ]

    ax1.legend(
        handles=pair_handles,
        loc="lower right",
        frameon=False,
        fontsize=8,
        handlelength=2.0,
        handletextpad=0.5,
    )

    # Save
    fig.savefig(out_pdf, bbox_inches="tight")
    if out_png is not None:
        fig.savefig(out_png, bbox_inches="tight", dpi=300)
    plt.close(fig)