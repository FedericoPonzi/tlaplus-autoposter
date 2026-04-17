"""Compute the 'By the Numbers' metrics table and manage history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from autoposter.models import CollectedData, MetricsSnapshot

__all__ = ["compute_metrics", "append_to_history"]

log = logging.getLogger(__name__)


def compute_metrics(collected: CollectedData) -> MetricsSnapshot:
    """Aggregate all repo-level stats into a single monthly snapshot.

    Sums numeric counters across every ``RepoStats`` entry and unions the
    contributor sets before taking their counts.
    """
    open_issues = 0
    merged_prs = 0
    commits = 0
    releases = 0
    active_contributors: set[str] = set()
    new_contributors: set[str] = set()

    for rs in collected.repo_stats:
        open_issues += rs.open_issues
        merged_prs += rs.merged_prs
        commits += rs.commits
        releases += rs.releases
        active_contributors |= rs.active_contributors
        new_contributors |= rs.new_contributors

    snapshot = MetricsSnapshot(
        month=collected.month,
        year=collected.year,
        open_issues=open_issues,
        merged_prs=merged_prs,
        commits=commits,
        releases=releases,
        active_contributors=len(active_contributors),
        new_contributors=len(new_contributors),
        google_group_messages=collected.google_group_message_count,
        tlc_runs=collected.tool_runs.tlc_runs,
        apalache_runs=collected.tool_runs.apalache_runs,
    )
    log.info(
        "Computed metrics for %02d/%d: %d PRs, %d commits, %d active contributors",
        snapshot.month,
        snapshot.year,
        snapshot.merged_prs,
        snapshot.commits,
        snapshot.active_contributors,
    )
    return snapshot


def append_to_history(
    snapshot: MetricsSnapshot,
    history_path: Path,
) -> list[dict]:
    """Append *snapshot* to the JSON history file, replacing any duplicate month.

    If an entry with the same ``month`` and ``year`` already exists it is
    replaced so that re-runs are idempotent.

    Returns the full history as a list of plain dicts.
    """
    if history_path.exists():
        history: list[dict] = json.loads(history_path.read_text())
    else:
        history = []

    new_entry = snapshot.to_dict()

    # Replace an existing entry for the same month/year, or append.
    replaced = False
    for idx, entry in enumerate(history):
        if entry.get("month") == snapshot.month and entry.get("year") == snapshot.year:
            history[idx] = new_entry
            replaced = True
            log.info("Replaced existing history entry for %02d/%d", snapshot.month, snapshot.year)
            break

    if not replaced:
        history.append(new_entry)
        log.info("Appended new history entry for %02d/%d", snapshot.month, snapshot.year)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2) + "\n")
    return history
