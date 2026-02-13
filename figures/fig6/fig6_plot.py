# fig6_plot.py
# Pure plotting (style + rendering) for QPU Fig.6.
#
# Layout: 3x2 grid (eta3 rows; signal/control columns).
# Each panel shows κ̂(z_rest) with amp_min on a twin axis and a dotted
# horizontal line at κ_eff.
#
# NEW: Spread ruler on right side showing q10-q90 range with κ_eff center mark.
#
# Style matched to fig4_sim_plot.py for consistency.

from __future__ import annotations

import math
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter


# -----------------------------------------------------------------------------
# Style (matched to fig4_sim_plot.py)
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
    "lines.markersize": 5,
}


FIG6_COLORS = {
    "signal_kappa": "#8175aa",   # muted violet (match Fig4)
    "control_kappa": "#607D8B",  # slate gray (match Fig4)
    "kappa_eff": "#444444",      # dark gray for scalar baseline
    "amp": "#555555",            # dark gray
    "ruler": "#222222",          # dark for ruler
}


def get_paper_style_rcparams() -> Dict[str, Any]:
    return dict(PAPER_STYLE_RCPARAMS)


def get_paper_style_manifest_rcparams() -> Dict[str, Any]:
    # JSON-friendly: avoid dots in keys
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
# Plotting helpers
# -----------------------------------------------------------------------------


def _nice_xticks(xs: np.ndarray, max_ticks: int = 9) -> np.ndarray:
    xs = np.asarray(xs, dtype=int)
    if xs.size <= max_ticks:
        return xs
    lo, hi = int(xs.min()), int(xs.max())
    ticks = np.linspace(lo, hi, num=max_ticks, dtype=int)
    ticks[0] = lo
    ticks[-1] = hi
    return np.unique(ticks)


def _draw_spread_ruler(
    ax,
    x_pos: float,
    kappa_eff: float,
    q10: float,
    q90: float,
    color_bar: str,
    color_center: str,
    bar_width: float = 1.5,
    center_width: float = 2.0,
) -> None:
    """Draw a spread ruler: thick translucent bar from q10 to q90 with thin center line at κ_eff."""
    from matplotlib.patches import Rectangle
    
    # Thick translucent bar (q10 to q90)
    rect = Rectangle(
        (x_pos - bar_width, q10),  # bottom-left corner
        bar_width * 2,              # width
        q90 - q10,                  # height
        facecolor=color_bar,
        edgecolor='none',
        alpha=0.35,
        zorder=10,
    )
    ax.add_patch(rect)
    
    # Thin solid line at κ_eff (contrasting with the bar)
    ax.hlines(
        kappa_eff, x_pos - center_width, x_pos + center_width,
        color=color_center,
        linewidth=1.8,
        alpha=1.0,
        zorder=11,
    )


def plot_fig6(
    *,
    panel_df: pd.DataFrame,
    panel_stats_df: pd.DataFrame,
    out_pdf: str,
    out_png: str | None = None,
    fig_size_inches: Tuple[float, float] = (6.967, 6.27),
    title: str | None = None,
    show_spread_ruler: bool = True,  # NEW: toggle spread ruler
) -> None:
    """Render QPU Fig.6 (η3 sweep) as a 3x2 grid.
    
    Style matched to fig4_sim_plot.py for visual consistency.
    
    NEW: show_spread_ruler adds a q10-q90 spread indicator on right side of each panel.
    """
    apply_paper_style()

    # Determine ordering
    eta_values = sorted({float(x) for x in panel_stats_df["eta3"].unique()})
    roles = ["signal", "control"]

    fig = plt.figure(figsize=fig_size_inches, constrained_layout=True)
    gs = fig.add_gridspec(len(eta_values), 2, width_ratios=[1.0, 1.0])
    fig.set_constrained_layout_pads(hspace=0.1)

    if title:
        fig.subtitle(rf"$\mathrm{{{title.replace(' ', r'\ ')}}}$", y=1.01, fontsize=14)

    # Panel labels A..F - mathtext
    panel_labels = [
        [r"$\mathbf{(A)}$", r"$\mathbf{(B)}$"],
        [r"$\mathbf{(C)}$", r"$\mathbf{(D)}$"],
        [r"$\mathbf{(E)}$", r"$\mathbf{(F)}$"],
    ]

    for r, eta in enumerate(eta_values):
        for c, role in enumerate(roles):
            ax = fig.add_subplot(gs[r, c])

            dfp = panel_df[(panel_df["eta3"] == float(eta)) & (panel_df["role"] == role)].sort_values(
                "z_rest_int"
            )
            if dfp.empty:
                ax.set_visible(False)
                continue

            stats = panel_stats_df[(panel_stats_df["eta3"] == float(eta)) & (panel_stats_df["role"] == role)]
            if stats.empty:
                ax.set_visible(False)
                continue
            stats_row = stats.iloc[0]

            pair = str(stats_row["pair"])
            kappa_eff = float(stats_row["kappa_eff"])

            z = dfp["z_rest_int"].to_numpy(dtype=int)
            k = dfp["kappa_hat"].to_numpy(dtype=float)
            amp = dfp["amp_min_ctx"].to_numpy(dtype=float)

            # Compute spread statistics for ruler
            q10 = float(np.percentile(k, 10))
            q90 = float(np.percentile(k, 90))

            # Colors
            if role == "signal":
                color_main = FIG6_COLORS["signal_kappa"]
            else:
                color_main = FIG6_COLORS["control_kappa"]
            color_amp = FIG6_COLORS["amp"]
            color_eff = FIG6_COLORS["kappa_eff"]

            # κ-hat
            ax.plot(
                z,
                k,
                marker="o",
                linestyle="-",
                color=color_main,
                markersize=3.5,
                linewidth=1.1,
                zorder=5,
            )
            ax.axhline(0.0, color="gray", linestyle="-", linewidth=0.8, alpha=0.5, zorder=1)

            # κ_eff (dotted, contrasting)
            if math.isfinite(kappa_eff):
                ax.axhline(
                    kappa_eff,
                    color=color_eff,
                    linestyle=":",
                    linewidth=2.0,
                    alpha=0.9,
                    zorder=2,
                )

            # Axes labels (only bottom row x-label)
            if r == len(eta_values) - 1:
                ax.set_xlabel(r"$\mathrm{context}\ z_{\mathrm{rest}}\ \mathrm{(int)}$")
            else:
                ax.set_xlabel("")
                ax.tick_params(axis="x", labelbottom=False)

            if c == 0:
                ax.set_ylabel(r"$\hat{\kappa}(z_{\mathrm{rest}})\ \mathrm{[rad]}$")
            else:
                ax.tick_params(axis="y", labelleft=False)

            # κ axis limits + ticks (already mathtext)
            ax.set_ylim(math.pi / 4 * 0.9, math.pi / 2 * 1.05)
            ax.set_yticks([math.pi / 4, 3 * math.pi / 8, math.pi / 2])
            ax.set_yticklabels([r"$\pi/4$", r"$3\pi/8$", r"$\pi/2$"])

            # X ticks and limits - extend right side for ruler
            z_max = int(z.max())
            z_min = int(z.min())
            xt = _nice_xticks(z)
            ax.set_xticks(xt)
            ax.xaxis.set_major_formatter(FuncFormatter(mathtext_formatter))
            
            if show_spread_ruler:
                # Extend x-axis to make room for ruler
                ax.set_xlim(z_min - 0.5, z_max + 5)
                
                # Draw spread ruler
                ruler_x = z_max + 3
                _draw_spread_ruler(
                    ax,
                    x_pos=ruler_x,
                    kappa_eff=kappa_eff,
                    q10=q10,
                    q90=q90,
                    color_bar=color_main,
                    color_center=color_main,
                    bar_width=0.6,
                    center_width=1.2,
                )
            else:
                ax.set_xlim(z_min - 0.5, z_max + 0.5)

            # amp_min on twin axis
            ax2 = ax.twinx()
            ax2.plot(
                z,
                amp,
                marker=".",
                linestyle="--",
                color=color_amp,
                markersize=2.5,
                linewidth=0.9,
                zorder=4,
            )
            ax2.set_ylim(0.0, 1.1)
            ax2.spines["right"].set_color(color_amp)
            ax2.tick_params(axis="y", colors=color_amp)
            ax2.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))
            if c == 1:
                ax2.set_ylabel(r"$\mathrm{amp}_{\min}$")
            else:
                ax2.set_ylabel("")
                ax2.tick_params(axis="y", labelright=False)

            # Title - all mathtext
            role_title = r"\mathrm{Signal}" if role == "signal" else r"\mathrm{Control}"
            n = int(stats_row["n"])
            ax.set_title(rf"${role_title}\ {pair},\ n={n},\ \eta_3={eta:g}$")

            # Panel label
            if r < len(panel_labels) and c < len(panel_labels[r]):
                ax.text(
                    -0.06,
                    1.04,
                    panel_labels[r][c],
                    transform=ax.transAxes,
                    fontsize=12,
                    va="bottom",
                    ha="right",
                )

    # Shared legend at bottom center (neutral colors, style only)
    legend_handles = [
        Line2D([0], [0], marker="o", linestyle="-", color="black", markersize=4, linewidth=1.1),
        Line2D([0], [0], linestyle=":", color="#444444", linewidth=2.0),
        Line2D([0], [0], marker=".", linestyle="--", color="#555555", markersize=3, linewidth=0.9),
    ]
    legend_labels = [
        r"$\hat{\kappa}(z_{\mathrm{rest}})$",
        r"$\hat{\kappa}^{\mathrm{eff}}\ \mathrm{(scalar)}$",
        r"$\mathrm{amp}_{\min}$",
    ]
    
    # Add spread ruler to legend if enabled
    if show_spread_ruler:
        from matplotlib.patches import Patch
        legend_handles.append(
            Patch(facecolor='gray', edgecolor='none', alpha=0.35)
        )
        legend_labels.append(r"$\mathrm{spread}\ (q_{10}\mathrm{-}q_{90})$")

    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        ncol=4 if show_spread_ruler else 3,
        frameon=True,
        framealpha=0.95,
        edgecolor="lightgray",
        fontsize=8,
        bbox_to_anchor=(0.5, -0.07),
    )

    print(f"Saving PDF to: {out_pdf}")
    fig.savefig(out_pdf, bbox_inches="tight")
    if out_png is not None:
        print(f"Saving PNG to: {out_png}")
        fig.savefig(out_png, bbox_inches="tight")

    plt.close(fig)