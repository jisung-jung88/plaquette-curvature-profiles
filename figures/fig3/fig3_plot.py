# fig3_plot.py
# Pure plotting (style + rendering) for Fig.3 (Simulation scaling report).
# MATCHED to Fig.5 Panel A/B Style (Exact Replica).
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
    # Ensure fonts are embedded as TrueType (avoid Type 3 glyph fonts in PDFs)
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.family": "serif",
    "font.serif": ["CMU Serif", "Computer Modern", "DejaVu Serif"],
    "mathtext.fontset": "cm",
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

# Deep & Rich Palette (Navy, Burgundy, Bottle Green) - Imported from Fig 5
COLOR_PALETTE = [
    "#4a6fa5",  # 0: slate blue       (eta=0.0)
    "#a85a6a",  # 1: dusty rose   (eta=0.1)
    "#5f8d75",  # 2: Sage Green (eta=0.2)
    "#8175aa",  # 3: Muted Violet       (Signal in Panel C - Contrast)
    "#d07e74",  # 4: Soft Brick
    "#e6a35c",  # 5: Sand/Ochre
]

# Fig.5 color conventions (shared)
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
    # JSON-friendly: avoid dots in keys (Required for make scripts)
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
# Plotter
# -----------------------------------------------------------------------------

def plot_fig3(
    *,
    summary_df: pd.DataFrame,
    out_pdf: str,
    out_png: str | None = None,
    fig_size_inches: Tuple[float, float] = (_FIGSIZE_WIDTH_IN, 4.40),
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (2, 3),
) -> None:
    """
    Fig.3 (Simulation): scaling report matching the visual language of Fig.5 Panels A & B.
    """
    apply_paper_style()

    required_cols = {"eta3", "n", "pair"}
    missing = required_cols - set(summary_df.columns)
    if missing:
        raise ValueError(f"summary_df missing required columns: {sorted(missing)}")

    # CI columns are optional; if absent, we plot without error bars.
    ylo_col = None
    yhi_col = None
    for lo, hi in [
        ("kappa_ctx_circ_var_ci95_lo", "kappa_ctx_circ_var_ci95_hi"),
        ("kappa_ctx_circ_var_shotbs_ci95_lo", "kappa_ctx_circ_var_shotbs_ci95_hi"),  # legacy
    ]:
        if lo in summary_df.columns and hi in summary_df.columns:
            ylo_col, yhi_col = lo, hi
            break

    # V_circ point column preference
    if "kappa_ctx_circ_var_point" in summary_df.columns:
        y_col = "kappa_ctx_circ_var_point"
    elif "kappa_ctx_circ_var_trial" in summary_df.columns:
        y_col = "kappa_ctx_circ_var_trial"
    else:
        raise ValueError("summary_df must contain either kappa_ctx_circ_var_point or kappa_ctx_circ_var_trial")

    # amp_min columns (required for Panel B)
    if "amp_min_mean_ctx_trial" not in summary_df.columns or "amp_min_q10_ctx_trial" not in summary_df.columns:
        raise ValueError("summary_df must contain amp_min_mean_ctx_trial and amp_min_q10_ctx_trial")

    # Layout: 2×1 vertical (A top, B bottom)
    fig = plt.figure(figsize=fig_size_inches, constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.1)

    axA = fig.add_subplot(gs[0, 0])
    axB = fig.add_subplot(gs[1, 0], sharex=axA)

    # Panel labels - mathtext
    for ax, label in zip([axA, axB], [r"$\mathbf{(A)}$", r"$\mathbf{(B)}$"]):
        ax.text(-0.02, 1.05, label, transform=ax.transAxes, fontsize=12, va="bottom", ha="right")

    # Color Mapping: Map eta to the first 3 colors (Blue, Red, Green)
    eta_vals = sorted(summary_df["eta3"].unique())
    color_map = {float(eta): FIG5_ETA_SWEEP_COLORS[k % len(FIG5_ETA_SWEEP_COLORS)] for k, eta in enumerate(eta_vals)}

    pair_styles = {
        f"({signal_pair[0]},{signal_pair[1]})": dict(
            marker="o", linestyle="-", markerfacecolor=None,
            label=f"Signal ({signal_pair[0]},{signal_pair[1]})", zorder=10
        ),
        f"({control_pair[0]},{control_pair[1]})": dict(
            marker="s", linestyle="--", markerfacecolor="white",
            label=f"Control ({control_pair[0]},{control_pair[1]})", zorder=10
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
            y = df[y_col].to_numpy()

            # CI bars (if available)
            if ylo_col is not None and yhi_col is not None:
                ylo = df[ylo_col].to_numpy()
                yhi = df[yhi_col].to_numpy()
                m = np.isfinite(x) & np.isfinite(ylo) & np.isfinite(yhi)
                cap = 0.12
                axA.vlines(x[m], ylo[m], yhi[m], color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
                axA.hlines(ylo[m], x[m] - cap, x[m] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
                axA.hlines(yhi[m], x[m] - cap, x[m] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)

            axA.plot(
                x, y,
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

    # Match y-axis range with Fig.5 Panel A
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

            # Whisker from q10 to mean (handles rare q10 > mean)
            m = np.isfinite(x) & np.isfinite(y) & np.isfinite(q10)
            cap = 0.12
            axB.vlines(x[m], q10[m], y[m], color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)
            axB.hlines(q10[m], x[m] - cap, x[m] + cap, color=c, linewidth=1.0, alpha=0.9, zorder=sty["zorder"] - 1)

            axB.plot(
                x, y,
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
    eta_vals_legend = sorted(eta_vals, reverse=True)

    # η₃ handles
    eta_handles = [
        Line2D([0], [0], color=color_map[float(e)], lw=2, label=rf"$\eta_3 = {e}$")
        for e in eta_vals_legend
    ]

    # pair handles
    pair_handles = [
        Line2D([0], [0], color="#333333", marker="o", linestyle="-", markersize=3.5,
            label=rf"$\mathrm{{Signal}}\ ({signal_pair[0]},{signal_pair[1]})$"),
        Line2D([0], [0], color="#333333", marker="s", linestyle="--", markerfacecolor="white", markersize=3.5,
            label=rf"$\mathrm{{Control}}\ ({control_pair[0]},{control_pair[1]})$"),
    ]

    # Left column: η₃ (vertical)
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

    # Right column: Signal/Control
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