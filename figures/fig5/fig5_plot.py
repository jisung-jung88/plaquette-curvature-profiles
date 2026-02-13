# fig5_plot.py
# Pure plotting (style + rendering) given already-computed figure data.
# UPDATED: Fig.5 now contains Panels A,B only (old Panel C moved to standalone Fig.6).
# Layout: 2×1 vertical (A top, B bottom), 246 pt column width.

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter


# -----------------------------------------------------------------------------
# PRA-matched editorial style
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

# Deep & rich palette (first three used for η3 sweep in ascending order)
COLOR_PALETTE = [
    "#4a6fa5",  # eta3=0.0
    "#a85a6a",  # eta3=0.1
    "#5f8d75",  # eta3=0.2
    "#8175aa",
    "#d07e74",
    "#e6a35c",
]

# Fig.5 color conventions (shared with manifest generation)
FIG5_ETA_SWEEP_COLORS = COLOR_PALETTE[:3]

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
    """rcParams, but JSON-friendly keys (dots replaced with underscores)."""
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


def plot_fig5(
    *,
    summary_df: pd.DataFrame,
    context_df: pd.DataFrame | None = None,  # kept for backward compatibility (unused)
    out_pdf: str,
    out_png: str | None = None,
    fig_size_inches: Tuple[float, float] = (_FIGSIZE_WIDTH_IN, 4.4),
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
) -> None:
    """Render UPDATED Fig.5 (Panels A,B only).

    Panel A: κ-profile dispersion V_circ vs n (η3 sweep; signal+control)
    Panel B: amp_min vs n (η3 sweep; signal+control)

    Notes:
      - The old representative κ-profile panel (previous Panel C) has been
        moved to a new standalone figure (Fig.6 in the updated blueprint).
      - `context_df` is accepted only to avoid breaking older scripts.
    """
    apply_paper_style()

    # Layout: 2×1 vertical (A top, B bottom)
    fig = plt.figure(figsize=fig_size_inches, constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.1)

    axA = fig.add_subplot(gs[0, 0])
    axB = fig.add_subplot(gs[1, 0], sharex=axA)

    # Panel labels - mathtext
    for ax, label in zip([axA, axB], [r"$\mathbf{(A)}$", r"$\mathbf{(B)}$"]):
        ax.text(-0.02, 1.05, label, transform=ax.transAxes, fontsize=12, va="bottom", ha="right")

    eta_vals = sorted(summary_df["eta3"].unique())
    color_map = {
        float(eta): FIG5_ETA_SWEEP_COLORS[k % len(FIG5_ETA_SWEEP_COLORS)]
        for k, eta in enumerate(eta_vals)
    }

    pair_styles = {
        f"({signal_pair[0]},{signal_pair[1]})": dict(
            marker="o",
            linestyle="-",
            markerfacecolor=None,
            label=f"Signal ({signal_pair[0]},{signal_pair[1]})",
            zorder=10,
        ),
        f"({control_pair[0]},{control_pair[1]})": dict(
            marker="s",
            linestyle="--",
            markerfacecolor="white",
            label=f"Control ({control_pair[0]},{control_pair[1]})",
            zorder=10,
        ),
    }

    ns = sorted(summary_df["n"].unique())
    xlims = (min(ns) - 0.5, max(ns) + 0.5)

    # -------------------------
    # Panel A: V_circ vs n
    # -------------------------
    for eta in eta_vals:
        c = color_map[float(eta)]
        for pair, sty in pair_styles.items():
            df = summary_df[(summary_df["eta3"] == eta) & (summary_df["pair"] == pair)].sort_values("n")
            if df.empty:
                continue

            x = df["n"].to_numpy()

            # Prefer reviewer-proof point estimate if present.
            y_col = "kappa_ctx_circ_var_point" if "kappa_ctx_circ_var_point" in df.columns else "kappa_ctx_circ_var_trial"
            y = df[y_col].to_numpy()

            ylo = df["kappa_ctx_circ_var_shotbs_ci95_lo"].to_numpy()
            yhi = df["kappa_ctx_circ_var_shotbs_ci95_hi"].to_numpy()

            # CI as explicit interval (no assumption point lies inside)
            m_ci = np.isfinite(x) & np.isfinite(ylo) & np.isfinite(yhi)
            cap = 0.12
            axA.vlines(x[m_ci], ylo[m_ci], yhi[m_ci], color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
            axA.hlines(ylo[m_ci], x[m_ci] - cap, x[m_ci] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
            axA.hlines(yhi[m_ci], x[m_ci] - cap, x[m_ci] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)

            axA.plot(
                x,
                y,
                color=c,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                markerfacecolor=sty["markerfacecolor"] if sty["markerfacecolor"] else c,
                markeredgewidth=1.2,
                markersize=3.5,
                linewidth=1.2,
                zorder=sty["zorder"],
            )

    axA.set_ylabel(r"$V_{\mathrm{circ}}$")
    axA.tick_params(labelbottom=False)
    axA.set_xticks(ns)
    axA.set_xlim(xlims)
    axA.xaxis.set_major_formatter(FuncFormatter(mathtext_formatter))
    axA.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))

    # Force same y-axis range as Fig.3 Panel A
    axA.set_ylim(-0.0008, 0.016)
    axA.set_yticks([0.0, 0.003, 0.006, 0.009, 0.012, 0.015])

    # -------------------------
    # Panel B: amp_min vs n
    # -------------------------
    for eta in eta_vals:
        c = color_map[float(eta)]
        for pair, sty in pair_styles.items():
            df = summary_df[(summary_df["eta3"] == eta) & (summary_df["pair"] == pair)].sort_values("n")
            if df.empty:
                continue

            x = df["n"].to_numpy()
            y = df["amp_min_mean_ctx_trial"].to_numpy()
            q10 = df["amp_min_q10_ctx_trial"].to_numpy()

            # Whisker from q10 to mean
            m_q = np.isfinite(x) & np.isfinite(y) & np.isfinite(q10)
            cap = 0.12
            axB.vlines(x[m_q], q10[m_q], y[m_q], color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
            axB.hlines(q10[m_q], x[m_q] - cap, x[m_q] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)

            axB.plot(
                x,
                y,
                color=c,
                marker=sty["marker"],
                linestyle=sty["linestyle"],
                markerfacecolor=sty["markerfacecolor"] if sty["markerfacecolor"] else c,
                markeredgewidth=1.2,
                markersize=3.5,
                linewidth=1.2,
                zorder=sty["zorder"],
            )

    axB.set_xlabel(r"$n\ \mathrm{(qubits)}$")
    axB.set_ylabel(r"$\mathrm{amp}_{\min}$")
    axB.set_xticks(ns)
    axB.set_xlim(xlims)
    axB.set_ylim(0.0, 1.1)
    axB.xaxis.set_major_formatter(FuncFormatter(mathtext_formatter))
    axB.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))

    # -------------------------
    # Legends inside panel (B) — data lives near y=0.85–1.0, lower region is clear
    # -------------------------
    # η3 legend (descending order for readability)
    eta_vals_legend = sorted(eta_vals, reverse=True)
    eta_handles = [
        Line2D([0], [0], color=color_map[float(e)], lw=2, label=rf"$\eta_3 = {e}$")
        for e in eta_vals_legend
    ]
    leg_eta = axB.legend(
        handles=eta_handles,
        loc="lower left",
        bbox_to_anchor=(0.02, 0.02),
        ncol=1,
        frameon=False,
        fontsize=8,
        handlelength=2.5,
    )
    axB.add_artist(leg_eta)

    pair_handles = [
        Line2D([0], [0], color="#333333", marker="o", linestyle="-", markersize=3.5, label=rf"$\mathrm{{Signal}}\ ({signal_pair[0]},{signal_pair[1]})$"),
        Line2D([0], [0], color="#333333", marker="s", linestyle="--", markerfacecolor="white", markersize=3.5, label=rf"$\mathrm{{Control}}\ ({control_pair[0]},{control_pair[1]})$"),
    ]

    axB.legend(
        handles=pair_handles,
        loc="lower left",
        bbox_to_anchor=(0.38, 0.133),
        ncol=1,
        frameon=False,
        fontsize=8,
        handlelength=2.5,
    )

    # Save
    print(f"Saving PDF to: {out_pdf}")
    fig.savefig(out_pdf, bbox_inches="tight")
    if out_png is not None:
        print(f"Saving PNG to: {out_png}")
        fig.savefig(out_png, bbox_inches="tight")

    plt.close(fig)