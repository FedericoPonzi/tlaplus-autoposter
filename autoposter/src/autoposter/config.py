"""Configuration loader for the autoposter pipeline.

Reads a YAML config file, resolves ``month: auto`` / ``year: auto`` to the
previous calendar month, and layers environment-variable overrides on top for
secrets and provider selection.
"""

from __future__ import annotations

import calendar
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

__all__ = [
    "Config",
    "RepoConfig",
    "LlmConfig",
    "MetabaseConfig",
    "GoogleGroupConfig",
    "GrantsConfig",
    "load_config",
]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root heuristic – the directory containing ``config.yaml``
# ---------------------------------------------------------------------------
_PROJECT_ROOT = None  # resolved lazily


def _get_project_root() -> Path:
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        from autoposter import PROJECT_ROOT
        _PROJECT_ROOT = PROJECT_ROOT
    return _PROJECT_ROOT


_DEFAULT_CONFIG_PATH = None  # resolved lazily


# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoConfig:
    """A single tracked GitHub repository."""

    name: str
    """Human-readable project name, e.g. ``'TLC'``."""

    slug: str
    """GitHub ``owner/repo`` slug, e.g. ``'tlaplus/tlaplus'``."""


@dataclass(frozen=True)
class LlmConfig:
    """LLM provider and model settings."""

    provider: str
    """One of ``azure_openai``, ``openai``, ``anthropic``, ``ollama``."""

    model: str
    """Model identifier passed to the provider (e.g. ``'gpt-4o'``)."""

    azure_deployment: str = ""
    """Azure OpenAI deployment name (used when *provider* is ``azure_openai``)."""

    azure_api_version: str = ""
    """Azure OpenAI API version string."""

    ollama_base_url: str = "http://localhost:11434"
    """Base URL for a local Ollama server."""

    api_key: str = ""
    """Resolved API key for the active provider (never from YAML)."""

    azure_endpoint: str = ""
    """Azure OpenAI endpoint URL (from ``AZURE_OPENAI_ENDPOINT``)."""


@dataclass(frozen=True)
class MetabaseConfig:
    """Metabase public-dashboard settings."""

    dashboard_url: str
    """URL of the public dashboard."""

    card_uuids: list[str] = field(default_factory=list)
    """UUIDs of specific cards to scrape (empty = all)."""


@dataclass(frozen=True)
class GoogleGroupConfig:
    """Google Group archive settings."""

    archive_url: str
    """URL of the mailing-list archive page."""


@dataclass(frozen=True)
class GrantsConfig:
    """TLA+ Foundation grants page settings."""

    url: str
    """URL of the grants listing page."""


# ---------------------------------------------------------------------------
# Top-level Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Fully-resolved, immutable configuration for a pipeline run."""

    month: int
    """Target month (1–12)."""

    year: int
    """Target year (e.g. 2026)."""

    repos: list[RepoConfig]
    """Tracked GitHub repositories."""

    llm: LlmConfig
    """LLM provider configuration."""

    metabase: MetabaseConfig
    """Metabase dashboard configuration."""

    google_group: GoogleGroupConfig
    """Google Group archive configuration."""

    grants: GrantsConfig
    """Grants page configuration."""

    target_repo: str
    """GitHub ``owner/repo`` slug where the blog-post PR is opened."""

    output_dir: str
    """Local directory for intermediate artefacts."""

    github_token: str = ""
    """GitHub API token (from ``GITHUB_TOKEN`` env var)."""

    # -- helper properties ---------------------------------------------------

    @property
    def month_name(self) -> str:
        """Full English month name, e.g. ``'January'``."""
        return calendar.month_name[self.month]

    @property
    def month_padded(self) -> str:
        """Zero-padded month number, e.g. ``'01'``."""
        return f"{self.month:02d}"

    @property
    def date_range(self) -> tuple[datetime, datetime]:
        """Inclusive start and *exclusive* end of the target month as datetimes.

        ``start`` is midnight on the 1st; ``end`` is midnight on the 1st of
        the following month (suitable for ``start <= dt < end`` comparisons).
        """
        start = datetime(self.year, self.month, 1)
        # Roll forward one month, handling December → January.
        if self.month == 12:
            end = datetime(self.year + 1, 1, 1)
        else:
            end = datetime(self.year, self.month + 1, 1)
        return start, end


# ---------------------------------------------------------------------------
# Auto-resolution helpers
# ---------------------------------------------------------------------------


def _resolve_auto_month_year(
    raw_month: int | str,
    raw_year: int | str,
) -> tuple[int, int]:
    """Return ``(month, year)`` after resolving ``'auto'`` values."""
    today = date.today()

    if str(raw_year).strip().lower() == "auto":
        year = today.year if today.month > 1 else today.year - 1
    else:
        year = int(raw_year)

    if str(raw_month).strip().lower() == "auto":
        if today.month == 1:
            month = 12
        else:
            month = today.month - 1
    else:
        month = int(raw_month)

    return month, year


def _resolve_llm_secrets(provider: str) -> tuple[str, str]:
    """Return ``(api_key, azure_endpoint)`` from environment variables.

    For ``azure_openai`` the key lookup order is
    ``AZURE_OPENAI_API_KEY`` → ``OPENAI_API_KEY``.
    """
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = ""

    if provider == "azure_openai":
        api_key = os.environ.get(
            "AZURE_OPENAI_API_KEY",
            os.environ.get("OPENAI_API_KEY", ""),
        )
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    return api_key, azure_endpoint


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = ("repos", "llm", "metabase", "google_group", "grants")


def _validate_raw(raw: dict) -> None:
    """Raise :class:`ValueError` when required fields are missing."""
    missing = [s for s in _REQUIRED_SECTIONS if s not in raw]
    if missing:
        raise ValueError(f"Missing required config sections: {', '.join(missing)}")

    if not raw.get("repos"):
        raise ValueError("'repos' must contain at least one entry")

    for i, repo in enumerate(raw["repos"]):
        if "slug" not in repo:
            raise ValueError(f"repos[{i}] is missing required field 'slug'")
        if "name" not in repo:
            raise ValueError(f"repos[{i}] is missing required field 'name'")

    llm = raw["llm"]
    if "provider" not in llm:
        raise ValueError("'llm.provider' is required")
    if "model" not in llm:
        raise ValueError("'llm.model' is required")

    if "dashboard_url" not in raw.get("metabase", {}):
        raise ValueError("'metabase.dashboard_url' is required")

    if "archive_url" not in raw.get("google_group", {}):
        raise ValueError("'google_group.archive_url' is required")

    if "url" not in raw.get("grants", {}):
        raise ValueError("'grants.url' is required")


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> Config:
    """Load, validate, and return a fully-resolved :class:`Config`.

    Parameters
    ----------
    path:
        Explicit path to a YAML config file.  When *None* the loader falls
        back to ``config.yaml`` in the autoposter project root.

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    ValueError
        If required fields are missing.
    """
    config_path = Path(path) if path is not None else (_get_project_root() / "config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    log.info("Loading config from %s", config_path)
    raw: dict = yaml.safe_load(config_path.read_text()) or {}

    _validate_raw(raw)

    # -- month / year --------------------------------------------------------
    month, year = _resolve_auto_month_year(
        raw.get("month", "auto"),
        raw.get("year", "auto"),
    )
    log.info("Resolved target period: %s %d", calendar.month_name[month], year)

    # -- repos ---------------------------------------------------------------
    repos = [RepoConfig(name=r["name"], slug=r["slug"]) for r in raw["repos"]]

    # -- llm -----------------------------------------------------------------
    llm_raw = raw["llm"]
    provider = os.environ.get("DEVUPDATE_LLM_PROVIDER", llm_raw["provider"])
    if provider != llm_raw["provider"]:
        log.info(
            "LLM provider overridden by DEVUPDATE_LLM_PROVIDER: %s → %s",
            llm_raw["provider"],
            provider,
        )

    api_key, azure_endpoint = _resolve_llm_secrets(provider)
    if not api_key and provider not in ("ollama",):
        log.warning("No API key found for LLM provider '%s'", provider)

    llm = LlmConfig(
        provider=provider,
        model=llm_raw["model"],
        azure_deployment=llm_raw.get("azure_deployment", ""),
        azure_api_version=llm_raw.get("azure_api_version", ""),
        ollama_base_url=llm_raw.get("ollama_base_url", "http://localhost:11434"),
        api_key=api_key,
        azure_endpoint=azure_endpoint,
    )

    # -- metabase ------------------------------------------------------------
    mb_raw = raw["metabase"]
    metabase = MetabaseConfig(
        dashboard_url=mb_raw["dashboard_url"],
        card_uuids=mb_raw.get("card_uuids", []),
    )

    # -- google group --------------------------------------------------------
    google_group = GoogleGroupConfig(archive_url=raw["google_group"]["archive_url"])

    # -- grants --------------------------------------------------------------
    grants = GrantsConfig(url=raw["grants"]["url"])

    # -- github token --------------------------------------------------------
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        log.warning("GITHUB_TOKEN is not set; GitHub API calls will be unauthenticated")

    return Config(
        month=month,
        year=year,
        repos=repos,
        llm=llm,
        metabase=metabase,
        google_group=google_group,
        grants=grants,
        target_repo=raw.get("target_repo", ""),
        output_dir=raw.get("output_dir", "output"),
        github_token=github_token,
    )
