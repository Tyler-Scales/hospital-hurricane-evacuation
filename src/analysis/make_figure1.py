"""Figure 1: flow of the cohort and registry into the analysis.

Regenerates manuscripts/figure1_flow.png and Final/figure1_flow.png. Counts are the
September 10, 2026 corrected build (Final/README.md); edit the strings below if they change.
Saved with a tight bounding box and padding so no box is clipped at the canvas edge.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

REPO = Path(__file__).resolve().parents[2]
fig, ax = plt.subplots(figsize=(15.7, 10.6))
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

def box(x, y, w, h, text, bold=False, size=15):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                fc="white", ec="black", lw=1.6))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size,
            fontweight="bold" if bold else "normal", family="serif", linespacing=1.5)

def arrow(x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="->", lw=1.6, color="black"))

# left column: cohort
box(1, 80, 44, 16, "Hospital–storm pairs threatened, 1990–2025\n80,189 pairs\n193 storms, 3,241 hospitals, 21 states + DC", bold=True)
arrow(23, 79.5, 23, 73)
box(1, 53, 44, 19, "Analytic period 2004–2025 (wind radii recorded)\n47,772 pairs\n17,811 (37%) inside the observed 34-kt wind field;\nthe rest entered through the forecast threat area")
ax.text(23, 41, "cohort supplies the denominator\nand every exposure variable", ha="center", va="center",
        fontsize=15, style="italic", family="serif", linespacing=1.5)
arrow(45.5, 61, 49.5, 41)

# right column: registry
box(50, 80, 49, 16, "Documented facility events (registry)\n261 events, 31 storms\nidentified from public reporting", bold=True)
arrow(74.5, 79.5, 74.5, 73)
box(50, 53, 49, 19, "Linked to a CMS certification number\n256 (188 automatic, 68 manual review)\n5 not linkable")
arrow(74.5, 52.5, 74.5, 46)
box(50, 26, 49, 19, "Inside the cohort: 228 events\nconsolidated to 214 hospital–storm pairs\n(30 storms, 156 hospitals; 14 events were a second\ncampus or facility under a certification already counted)\n28 outside: non-acute facilities or outside the threat area", size=13)
arrow(74.5, 25.5, 74.5, 20)
box(50, 2, 49, 17, "Sheltering pairs, 2004–2025: 114 (41 FSIP)\nLevee-protected, separate stratum: 18 (12 FSIP)\nPrimary model: 96 pairs (29 FSIP)\n1990–2003 pairs, described only: 11 (4 FSIP)", bold=True, size=14)

for out in (REPO / "manuscripts" / "figure1_flow.png", REPO / "Final" / "figure1_flow.png"):
    fig.savefig(out, dpi=110, bbox_inches="tight", pad_inches=0.25, facecolor="white")
    print("wrote", out)
