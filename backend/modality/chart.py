"""
Auto chart generation from query results using matplotlib.
Returns PNG image bytes.
"""

import io
import matplotlib

matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


def generate_chart(rows: list[dict], chart_type: str = "auto") -> bytes | None:
    """
    Generate a chart from query result rows.
    Returns PNG bytes or None if data isn't chartable.
    """
    if not rows or len(rows) < 2:
        return None

    cols = list(rows[0].keys())

    # Find numeric and label columns
    numeric_cols = [c for c in cols if isinstance(rows[0][c], (int, float))]
    label_cols = [c for c in cols if c not in numeric_cols]

    if not numeric_cols:
        return None

    # Auto-detect chart type
    if chart_type == "auto":
        chart_type = _detect_chart_type(rows, cols, label_cols, numeric_cols)

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#fafafa")
    ax.set_facecolor("#fafafa")

    if chart_type == "line":
        _draw_line(ax, rows, label_cols, numeric_cols)
    elif chart_type == "bar":
        _draw_bar(ax, rows, label_cols, numeric_cols)
    elif chart_type == "horizontal_bar":
        _draw_hbar(ax, rows, label_cols, numeric_cols)
    else:
        _draw_bar(ax, rows, label_cols, numeric_cols)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _detect_chart_type(rows, cols, label_cols, numeric_cols) -> str:
    """Heuristic to pick the best chart type."""
    # If first label col looks like a date → line chart
    if label_cols:
        sample = str(rows[0][label_cols[0]])
        if len(sample) == 10 and sample[4] == "-":  # YYYY-MM-DD
            return "line"

    # If many rows with short labels → horizontal bar
    if len(rows) > 8:
        return "horizontal_bar"

    return "bar"


def _draw_line(ax, rows, label_cols, numeric_cols):
    labels = [
        str(r[label_cols[0]]) if label_cols else str(i) for i, r in enumerate(rows)
    ]
    for nc in numeric_cols[:3]:  # max 3 lines
        values = [r[nc] for r in rows]
        ax.plot(labels, values, marker="o", markersize=3, linewidth=1.5, label=nc)
    ax.legend(fontsize=8)
    # Thin out x-axis labels if too many
    if len(labels) > 15:
        ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=10))
    plt.xticks(rotation=45, ha="right", fontsize=7)


def _draw_bar(ax, rows, label_cols, numeric_cols):
    labels = [
        str(r[label_cols[0]])[:25] if label_cols else str(i) for i, r in enumerate(rows)
    ]
    values = [r[numeric_cols[0]] for r in rows]
    colors = plt.cm.Blues(
        [0.4 + 0.5 * i / max(len(values) - 1, 1) for i in range(len(values))]
    )
    ax.bar(labels, values, color=colors)
    ax.set_ylabel(numeric_cols[0], fontsize=9)
    plt.xticks(rotation=45, ha="right", fontsize=7)


def _draw_hbar(ax, rows, label_cols, numeric_cols):
    labels = [
        str(r[label_cols[0]])[:30] if label_cols else str(i) for i, r in enumerate(rows)
    ]
    values = [r[numeric_cols[0]] for r in rows]
    colors = plt.cm.Blues(
        [0.4 + 0.5 * i / max(len(values) - 1, 1) for i in range(len(values))]
    )
    ax.barh(labels, values, color=colors)
    ax.set_xlabel(numeric_cols[0], fontsize=9)
    ax.invert_yaxis()
