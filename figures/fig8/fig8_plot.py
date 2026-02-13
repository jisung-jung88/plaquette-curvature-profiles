# fig8_plot.py
# Pure plotting/styling for Appendix Fig. 8.
#
# Inputs:
#   - day1/day2 precomputed DataFrames from fig8_data.compute_fig8_day_products
#
# Output:
#   - PDF (and optional PNG) figure.

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MultipleLocator


# -----------------------------------------------------------------------------
# Paper style (mirrors fig5_plot so the whole paper is consistent)
# -----------------------------------------------------------------------------
PAPER_STYLE_RCPARAMS: Dict[str, Any] = {
    "figure.dpi": 300,
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
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
}

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
    """A JSON-friendly rcparams dict (same convention as Fig.5 manifest)."""
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
# Fig.9 styling knobs (EDIT HERE when you want to tweak the look)
# -----------------------------------------------------------------------------

# Day-to-day colors for Panel B (signal/control breakdown)
fig8_DAY_COLORS = {
    "Day1": "#548c8d",  
    "Day2": "#c2a855", 
}

# Day-to-day colors for Panel A (delta mode) - distinct from Fig3 signal/control
fig8_DELTA_COLORS = {
    "Day1": "#548c8d",  
    "Day2": "#c2a855", 
}

# Marker for Panel A delta mode (distinct from signal/control markers)
fig8_DELTA_MARKER = "^"  # thin diamond (smaller footprint than "D")
fig8_DELTA_MARKERSIZE = 3.5  # slightly smaller than default 6

# Pair styles (consistent with Fig.5: signal is solid, control is dashed)
fig8_PAIR_STYLES = {
    "signal": dict(marker="o", linestyle="-", markerfacecolor=None),
    "control": dict(marker="s", linestyle="--", markerfacecolor="white"),
}


def _etas_intersection(day1_df: pd.DataFrame, day2_df: pd.DataFrame, col: str = "eta3") -> list[float]:
    e1 = {float(x) for x in day1_df[col].unique()}
    e2 = {float(x) for x in day2_df[col].unique()}
    return sorted(e1.intersection(e2))


def plot_fig8(
    *,
    day1_summary_df: pd.DataFrame,
    day2_summary_df: pd.DataFrame,
    day1_delta_df: pd.DataFrame,
    day2_delta_df: pd.DataFrame,
    out_pdf: str,
    out_png: str | None = None,
    n_key: int = 7,
    metric_mode: str = "delta",  # {"delta", "V"}
    signal_pair: Tuple[int, int] = (0, 1),
    control_pair: Tuple[int, int] = (1, 4),
    include_control_amp: bool = True,
    fig_size_inches: Tuple[float, float] = (_FIGSIZE_WIDTH_IN, 4.3),
) -> None:
    """Render Appendix Fig. 9.

    Panel A: Day1 vs Day2 overlay for either
      - ΔV_circ(eta3) at fixed n (default), or
      - V_circ(eta3) at fixed n for both signal+control.

    Panel B: amp_min whiskers (q10 -> mean) at fixed n.
    """

    metric_mode = str(metric_mode).lower().strip()
    if metric_mode not in {"delta", "v"}:
        raise ValueError("metric_mode must be one of {'delta','V'}.")

    apply_paper_style()

    # Determine which eta values are comparable across days.
    if metric_mode == "delta":
        etas = _etas_intersection(day1_delta_df[day1_delta_df["n"] == int(n_key)], day2_delta_df[day2_delta_df["n"] == int(n_key)])
    else:
        etas = _etas_intersection(day1_summary_df[day1_summary_df["n"] == int(n_key)], day2_summary_df[day2_summary_df["n"] == int(n_key)])

    if len(etas) == 0:
        raise ValueError(f"No overlapping eta3 values found between Day1 and Day2 at n={n_key}.")

    # Use categorical x positions for clean offsets.
    x0 = np.arange(len(etas), dtype=float)
    xticklabels = [rf"${e:g}$" for e in etas]

    # Offsets: day and pair are separated so points don't collide.
    off_day = {"Day1": -0.15, "Day2": +0.15}
    off_pair = {"signal": -0.05, "control": +0.05}

    # Layout: 2x1 stacked (matches fig7_plot style)
    fig = plt.figure(figsize=fig_size_inches, constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[1, 1], hspace=0.1)

    axA = fig.add_subplot(gs[0, 0])
    axB = fig.add_subplot(gs[1, 0], sharex=axA)

    # Panel labels - mathtext
    axA.text(-0.02, 1.05, r"$\mathbf{(A)}$", transform=axA.transAxes, fontsize=12, va="bottom", ha="right")
    axB.text(-0.02, 1.05, r"$\mathbf{(B)}$", transform=axB.transAxes, fontsize=12, va="bottom", ha="right")

    # ------------------------------------------------------------------
    # Panel A
    # ------------------------------------------------------------------
    if metric_mode == "delta":
        for day_label, ddf in [("Day1", day1_delta_df), ("Day2", day2_delta_df)]:
            df = ddf[ddf["n"] == int(n_key)].set_index("eta3")
            df = df.loc[etas]
            y = df["delta_V_circ"].to_numpy(float)
            lo = df["delta_shotbs_ci_lo"].to_numpy(float)
            hi = df["delta_shotbs_ci_hi"].to_numpy(float)

            x = x0 + off_day[day_label]
            yerr = np.vstack([y - lo, hi - y])
            c = fig8_DELTA_COLORS[day_label]
            axA.errorbar(
                x,
                y,
                yerr=yerr,
                fmt=fig8_DELTA_MARKER,
                markersize=fig8_DELTA_MARKERSIZE,
                color=c,
                markerfacecolor=c,
                markeredgewidth=1.2,
                capsize=3,
                linewidth=1.2,
                label=rf"$\mathrm{{{day_label}}}$",
                zorder=10,
            )
            axA.plot(x, y, color=c, linewidth=1.2, zorder=9)

        axA.set_ylabel(r"$\Delta V_{\mathrm{circ}}$")
        axA.set_ylim(-0.001, 0.013)
        axA.yaxis.set_major_locator(MultipleLocator(0.002))

    else:
        pair_map = {
            "signal": f"({signal_pair[0]},{signal_pair[1]})",
            "control": f"({control_pair[0]},{control_pair[1]})",
        }
        for day_label, sdf in [("Day1", day1_summary_df), ("Day2", day2_summary_df)]:
            for role, pair_str in pair_map.items():
                df = sdf[(sdf["n"] == int(n_key)) & (sdf["pair"] == pair_str)].set_index("eta3")
                df = df.loc[etas]
                y = df["kappa_ctx_circ_var_point"].to_numpy(float)
                lo = df["kappa_ctx_circ_var_shotbs_ci95_lo"].to_numpy(float)
                hi = df["kappa_ctx_circ_var_shotbs_ci95_hi"].to_numpy(float)

                x = x0 + off_day[day_label] + off_pair[role]
                yerr = np.vstack([y - lo, hi - y])
                sty = fig8_PAIR_STYLES[role]

                axA.errorbar(
                    x,
                    y,
                    yerr=yerr,
                    fmt=sty["marker"],
                    markersize=3.5,
                    color=fig8_DAY_COLORS[day_label],
                    markerfacecolor=(fig8_DAY_COLORS[day_label] if sty["markerfacecolor"] is None else sty["markerfacecolor"]),
                    markeredgewidth=1.2,
                    capsize=3,
                    linewidth=1.0,
                    zorder=10 if role == "signal" else 9,
                )
                axA.plot(
                    x,
                    y,
                    color=fig8_DAY_COLORS[day_label],
                    linestyle=sty["linestyle"],
                    linewidth=1.2,
                    zorder=8,
                )

        axA.set_ylabel(r"$\kappa\mathrm{-profile\ dispersion}\ V_{\mathrm{circ}}$")

    axA.set_xlabel("")
    axA.tick_params(labelbottom=False)
    axA.set_xticks(x0)
    axA.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))

    # ------------------------------------------------------------------
    # Panel B (amp_min quality)
    # ------------------------------------------------------------------
    pair_map_amp = {"signal": f"({signal_pair[0]},{signal_pair[1]})"}
    if include_control_amp:
        pair_map_amp["control"] = f"({control_pair[0]},{control_pair[1]})"

    for day_label, sdf in [("Day1", day1_summary_df), ("Day2", day2_summary_df)]:
        for role, pair_str in pair_map_amp.items():
            df = sdf[(sdf["n"] == int(n_key)) & (sdf["pair"] == pair_str)].set_index("eta3")
            df = df.loc[etas]
            mean = df["amp_min_mean_ctx_trial"].to_numpy(float)
            q10 = df["amp_min_q10_ctx_trial"].to_numpy(float)

            x = x0 + off_day[day_label] + off_pair[role]
            c = fig8_DAY_COLORS[day_label]
            sty = fig8_PAIR_STYLES[role]

            # Whisker q10 -> mean (works even if q10 > mean in weird edge cases)
            cap = 0.06
            m = np.isfinite(x) & np.isfinite(mean) & np.isfinite(q10)
            axB.vlines(x[m], q10[m], mean[m], color=c, linewidth=1.0, alpha=0.95, zorder=8)
            axB.hlines(q10[m], x[m] - cap, x[m] + cap, color=c, linewidth=1.0, alpha=0.95, zorder=8)
            axB.plot(
                x,
                mean,
                color=c,
                linestyle=sty["linestyle"],
                marker=sty["marker"],
                markerfacecolor=(c if sty["markerfacecolor"] is None else sty["markerfacecolor"]),
                markeredgewidth=1.2,
                markersize=3.5,
                linewidth=1.2,
                zorder=10 if role == "signal" else 9,
            )

    axB.set_xlabel(r"$\eta_3$")
    axB.set_ylabel(r"$\mathrm{amp}_{\min}$")
    axB.set_xticks(x0)
    axB.set_xticklabels(xticklabels)
    axB.set_ylim(0.0, 1.1)
    axB.yaxis.set_major_formatter(FuncFormatter(mathtext_formatter))

    # ------------------------------------------------------------------
    # Legend inside panel (B) — data lives near y=0.9–1.0, lower-right is clear
    # ------------------------------------------------------------------
    delta_day_handles = [
        Line2D([0], [0], color=fig8_DELTA_COLORS["Day1"], marker=fig8_DELTA_MARKER, linestyle="-", markersize=fig8_DELTA_MARKERSIZE, label=r"$\mathrm{Day1}$"),
        Line2D([0], [0], color=fig8_DELTA_COLORS["Day2"], marker=fig8_DELTA_MARKER, linestyle="-", markersize=fig8_DELTA_MARKERSIZE, label=r"$\mathrm{Day2}$"),
    ]

    pair_handles = [
        Line2D([0], [0], color="#333333", marker=fig8_PAIR_STYLES["signal"]["marker"], linestyle=fig8_PAIR_STYLES["signal"]["linestyle"], markersize=3.5, label=rf"$\mathrm{{Signal}}\ ({signal_pair[0]},{signal_pair[1]})$"),
        Line2D([0], [0], color="#333333", marker=fig8_PAIR_STYLES["control"]["marker"], linestyle=fig8_PAIR_STYLES["control"]["linestyle"], markerfacecolor="white", markersize=3.5, label=rf"$\mathrm{{Control}}\ ({control_pair[0]},{control_pair[1]})$"),
    ]

    axB.legend(
        handles=delta_day_handles + pair_handles,
        loc="lower right",
        ncol=2,
        frameon=False,
        fontsize=8,
        handlelength=2.0,
        handletextpad=0.5,
        columnspacing=1.2,
    )

    # Save
    fig.savefig(out_pdf, bbox_inches="tight")
    if out_png:
        fig.savefig(out_png,  bbox_inches="tight", dpi=300)
    plt.close(fig)