"""Render SVG trend charts from metrics history using pygal."""

from __future__ import annotations

import calendar
import logging
from pathlib import Path

import pygal
from pygal.style import CleanStyle

__all__ = ["render_charts"]

log = logging.getLogger(__name__)


def _month_label(entry: dict) -> str:
    """Return a short month label like 'Jan 2025'."""
    return f"{calendar.month_abbr[entry['month']]} {entry['year']}"


def _make_chart(
    title: str,
    labels: list[str],
    series_name: str,
    values: list[int],
) -> pygal.Line:
    """Create a clean, minimal line chart."""
    chart = pygal.Line(
        title=title,
        x_title="Month",
        y_title="Count",
        style=CleanStyle,
        show_legend=False,
        x_label_rotation=45,
        width=800,
        height=400,
        dots_size=3,
        show_minor_x_labels=True,
    )
    chart.x_labels = labels
    chart.add(series_name, values)
    return chart


def render_charts(history: list[dict], output_dir: Path) -> list[Path]:
    """Render SVG line charts from the metrics history.

    Produces three charts:

    * ``prs_per_month.svg`` — merged PRs per month
    * ``commits_per_month.svg`` — commits per month
    * ``active_contributors_per_month.svg`` — active contributors per month

    Parameters
    ----------
    history:
        List of ``MetricsSnapshot`` dicts, as returned by
        :func:`autoposter.builder.metrics.append_to_history`.
    output_dir:
        Directory where SVG files will be written (created if missing).

    Returns
    -------
    list[Path]
        Paths of the generated SVG files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if not history:
        log.warning("Empty history — no charts to render")
        return []

    # Sort chronologically so the x-axis is in order.
    sorted_history = sorted(history, key=lambda e: (e["year"], e["month"]))
    labels = [_month_label(e) for e in sorted_history]

    chart_specs: list[tuple[str, str, str]] = [
        ("Merged PRs per Month", "merged_prs", "prs_per_month.svg"),
        ("Commits per Month", "commits", "commits_per_month.svg"),
        ("Active Contributors per Month", "active_contributors", "active_contributors_per_month.svg"),
    ]

    created: list[Path] = []
    for title, key, filename in chart_specs:
        values = [e.get(key, 0) for e in sorted_history]
        chart = _make_chart(title, labels, key, values)
        path = output_dir / filename
        chart.render_to_file(str(path))
        log.info("Rendered %s", path)
        created.append(path)

    return created
