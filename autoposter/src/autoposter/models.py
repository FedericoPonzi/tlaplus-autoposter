"""Shared data models used across all pipeline stages.

These dataclasses define the contracts between Collect, Summarize, Build, and PR
stages.  Every stage reads/writes these types serialized as JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Self


# ---------------------------------------------------------------------------
# Collect stage outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectedItem:
    """A single item collected from a data source (PR, issue, or release)."""

    source_repo: str
    """GitHub slug, e.g. 'tlaplus/tlaplus'."""

    project_name: str
    """Human-readable project name, e.g. 'TLC'."""

    title: str
    """PR / issue / release title."""

    url: str
    """Canonical URL for linking."""

    kind: str
    """One of 'pr', 'issue', 'release'."""

    number: int
    """PR or issue number."""

    merged_at: str | None = None
    """ISO-8601 timestamp of merge (PRs only)."""

    author: str = ""
    """GitHub username of the author."""

    description: str = ""
    """Body text of the PR / issue / release."""

    changelog_body: str | None = None
    """If a ```changelog``` fence was found, its contents verbatim."""


@dataclass
class RepoStats:
    """Aggregate statistics for a single repository in a given month."""

    repo_slug: str
    open_issues: int = 0
    merged_prs: int = 0
    commits: int = 0
    releases: int = 0
    active_contributors: set[str] = field(default_factory=set)
    new_contributors: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (sets → sorted lists)."""
        d = asdict(self)
        d["active_contributors"] = sorted(self.active_contributors)
        d["new_contributors"] = sorted(self.new_contributors)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        data = dict(data)
        data["active_contributors"] = set(data.get("active_contributors", []))
        data["new_contributors"] = set(data.get("new_contributors", []))
        return cls(**data)


@dataclass
class CommunityThread:
    """A notable thread from the TLA+ Google Group."""

    subject: str
    url: str
    reply_count: int
    date: str
    """ISO-8601 date of the first message."""

    is_notable: bool = False
    """True when reply_count > 2."""


@dataclass
class GrantInfo:
    """A grant listed on the TLA+ Foundation grants page."""

    title: str
    url: str
    description: str = ""


@dataclass
class ToolRunStats:
    """Tool-run counts from the Metabase public dashboard."""

    tlc_runs: int = 0
    apalache_runs: int = 0


# ---------------------------------------------------------------------------
# Cross-stage aggregates
# ---------------------------------------------------------------------------

@dataclass
class MetricsSnapshot:
    """All 'By the Numbers' metrics for a single month."""

    month: int
    year: int
    open_issues: int = 0
    merged_prs: int = 0
    commits: int = 0
    releases: int = 0
    active_contributors: int = 0
    new_contributors: int = 0
    google_group_messages: int = 0
    tlc_runs: int = 0
    apalache_runs: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return cls(**data)


@dataclass
class CollectedData:
    """Complete output of the Collect stage — everything needed by later stages."""

    month: int
    year: int
    items: list[CollectedItem] = field(default_factory=list)
    repo_stats: list[RepoStats] = field(default_factory=list)
    community_threads: list[CommunityThread] = field(default_factory=list)
    grants: list[GrantInfo] = field(default_factory=list)
    tool_runs: ToolRunStats = field(default_factory=ToolRunStats)
    google_group_message_count: int = 0

    # -- JSON serialization --------------------------------------------------

    def save(self, path: Path) -> None:
        """Write collected data to a JSON file."""
        path.write_text(json.dumps(self._to_dict(), indent=2, default=str))

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read collected data from a JSON file."""
        data = json.loads(path.read_text())
        return cls._from_dict(data)

    def _to_dict(self) -> dict:
        return {
            "month": self.month,
            "year": self.year,
            "items": [asdict(i) for i in self.items],
            "repo_stats": [rs.to_dict() for rs in self.repo_stats],
            "community_threads": [asdict(t) for t in self.community_threads],
            "grants": [asdict(g) for g in self.grants],
            "tool_runs": asdict(self.tool_runs),
            "google_group_message_count": self.google_group_message_count,
        }

    @classmethod
    def _from_dict(cls, data: dict) -> Self:
        return cls(
            month=data["month"],
            year=data["year"],
            items=[CollectedItem(**i) for i in data.get("items", [])],
            repo_stats=[RepoStats.from_dict(rs) for rs in data.get("repo_stats", [])],
            community_threads=[
                CommunityThread(**t) for t in data.get("community_threads", [])
            ],
            grants=[GrantInfo(**g) for g in data.get("grants", [])],
            tool_runs=ToolRunStats(**data.get("tool_runs", {})),
            google_group_message_count=data.get("google_group_message_count", 0),
        )


@dataclass
class SummarizedData:
    """Output of the Summarize stage — ready for rendering."""

    month: int
    year: int
    intro: str = ""
    dev_update_bullets: list[str] = field(default_factory=list)
    community_bullets: list[str] = field(default_factory=list)
    metrics: MetricsSnapshot | None = None

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "month": self.month,
                    "year": self.year,
                    "intro": self.intro,
                    "dev_update_bullets": self.dev_update_bullets,
                    "community_bullets": self.community_bullets,
                    "metrics": self.metrics.to_dict() if self.metrics else None,
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text())
        return cls(
            month=data["month"],
            year=data["year"],
            intro=data.get("intro", ""),
            dev_update_bullets=data.get("dev_update_bullets", []),
            community_bullets=data.get("community_bullets", []),
            metrics=(
                MetricsSnapshot.from_dict(data["metrics"])
                if data.get("metrics")
                else None
            ),
        )
