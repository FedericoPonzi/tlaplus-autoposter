"""Collector that fetches merged PRs, releases, and repo stats from GitHub.

Uses a **hybrid git + API** approach to minimise API rate-limit consumption:

* **Git-based** (zero API calls): bare blobless clones are cached locally and
  used for commit counts, active/new contributor detection (via ``%aN`` with
  mailmap support).
* **API-based** (minimal calls): the GitHub Search API finds merged PRs in one
  request; releases and open-issue counts use one call each.

Authenticates with a personal-access token passed explicitly or read from the
``GITHUB_TOKEN`` environment variable.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from autoposter.models import CollectedItem, RepoStats

__all__ = ["collect_github"]

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_PER_PAGE = 100
_RATE_LIMIT_BUFFER = 3  # sleep when remaining requests drop below this
_CHANGELOG_RE = re.compile(
    r"```changelog\s*\n(.*?)```", re.DOTALL,
)
_DEFAULT_CACHE_DIR = Path("/tmp/autoposter-repo-cache")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git command and return its stdout (stripped).

    Raises ``subprocess.CalledProcessError`` on non-zero exit.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _ensure_bare_clone(owner: str, repo: str, cache_dir: Path) -> Path:
    """Clone or fetch a bare blobless mirror of *owner/repo*.

    Returns the path to the bare repo directory.
    """
    repo_dir = cache_dir / owner / f"{repo}.git"
    if repo_dir.exists():
        logger.debug("Fetching updates for %s/%s …", owner, repo)
        _run_git(["fetch", "origin"], cwd=repo_dir)
    else:
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{owner}/{repo}.git"
        logger.info("Cloning %s (bare, blobless) …", url)
        subprocess.run(
            [
                "git", "clone", "--bare", "--filter=blob:none",
                url, str(repo_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return repo_dir


def _resolve_default_branch(repo_dir: Path) -> str:
    """Determine the default branch for a bare clone.

    Tries ``refs/remotes/origin/HEAD``, then falls back to checking for
    ``refs/heads/main`` or ``refs/heads/master``.
    """
    try:
        ref = _run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_dir,
        )
        # e.g. "refs/remotes/origin/main" → "main"
        return ref.rsplit("/", 1)[-1]
    except subprocess.CalledProcessError:
        pass

    # Fallback: check which well-known branch exists
    for candidate in ("main", "master"):
        try:
            _run_git(
                ["rev-parse", "--verify", f"refs/heads/{candidate}"],
                cwd=repo_dir,
            )
            return candidate
        except subprocess.CalledProcessError:
            continue

    # Last resort
    return "main"


def _git_commit_count(
    repo_dir: Path,
    branch: str,
    after: str,
    before: str,
) -> int:
    """Count commits on *branch* in the half-open range (after, before)."""
    output = _run_git(
        [
            "log", branch, "--oneline", "--use-mailmap",
            f"--after={after}", f"--before={before}",
        ],
        cwd=repo_dir,
    )
    if not output:
        return 0
    return len(output.splitlines())


def _git_active_contributors(
    repo_dir: Path,
    branch: str,
    after: str,
    before: str,
) -> set[str]:
    """Return the set of unique author names (mailmap-resolved) in the range."""
    output = _run_git(
        [
            "log", branch, "--format=%aN", "--use-mailmap",
            f"--after={after}", f"--before={before}",
        ],
        cwd=repo_dir,
    )
    if not output:
        return set()
    return set(output.splitlines())


def _git_historical_contributors(
    repo_dir: Path,
    branch: str,
    before: str,
) -> set[str]:
    """Return all author names that committed before the given date."""
    output = _run_git(
        [
            "log", branch, "--format=%aN", "--use-mailmap",
            f"--before={before}",
        ],
        cwd=repo_dir,
    )
    if not output:
        return set()
    return set(output.splitlines())


# ---------------------------------------------------------------------------
# HTTP / API helpers
# ---------------------------------------------------------------------------

def _build_client(github_token: str | None) -> httpx.Client:
    """Return a configured ``httpx.Client`` with auth & accept headers."""
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return httpx.Client(
        base_url=_GITHUB_API,
        headers=headers,
        timeout=30.0,
        follow_redirects=True,
    )


def _check_rate_limit(response: httpx.Response) -> None:
    """Sleep until the reset window if the remaining quota is nearly exhausted."""
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is None:
        return
    if int(remaining) < _RATE_LIMIT_BUFFER:
        reset_ts = int(response.headers.get("X-RateLimit-Reset", "0"))
        sleep_for = max(reset_ts - int(time.time()), 1) + 1
        logger.warning(
            "Rate-limit nearly exhausted (%s remaining). Sleeping %ds …",
            remaining,
            sleep_for,
        )
        time.sleep(sleep_for)


def _get_json(client: httpx.Client, url: str, params: dict | None = None) -> list | dict:
    """GET *url*, return parsed JSON, raising on HTTP errors."""
    resp = client.get(url, params=params)
    _check_rate_limit(resp)
    resp.raise_for_status()
    return resp.json()


def _parse_next_link(link_header: str) -> str | None:
    """Extract the ``next`` URL from a GitHub ``Link`` header."""
    for part in link_header.split(","):
        if 'rel="next"' in part:
            url = part.split(";")[0].strip().strip("<>")
            return url
    return None


def _paginate(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    *,
    max_pages: int = 50,
) -> list[dict]:
    """Paginate through a GitHub list endpoint following ``Link`` headers."""
    params = dict(params or {})
    params.setdefault("per_page", str(_PER_PAGE))
    collected: list[dict] = []

    next_url: str | None = url
    page = 0
    while next_url and page < max_pages:
        resp = client.get(next_url, params=params if page == 0 else None)
        _check_rate_limit(resp)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            collected.extend(data)
        else:
            collected.append(data)

        next_url = _parse_next_link(resp.headers.get("Link", ""))
        page += 1

    return collected


def _search_paginate(
    client: httpx.Client,
    params: dict,
    *,
    max_pages: int = 10,
) -> list[dict]:
    """Paginate through the GitHub *search/issues* endpoint.

    The search API embeds results inside ``{"items": [...]}``.  We follow
    ``Link`` headers for pagination.
    """
    url: str | None = "/search/issues"
    params = dict(params)
    params.setdefault("per_page", str(_PER_PAGE))
    collected: list[dict] = []

    page = 0
    while url and page < max_pages:
        resp = client.get(url, params=params if page == 0 else None)
        _check_rate_limit(resp)
        resp.raise_for_status()
        data = resp.json()
        collected.extend(data.get("items", []))

        url = _parse_next_link(resp.headers.get("Link", ""))
        page += 1

    return collected


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _month_boundaries(year: int, month: int) -> tuple[date, date, date]:
    """Return ``(month_start, month_end, next_month_start)`` as dates."""
    month_start = date(year, month, 1)
    _, last_day = monthrange(year, month)
    month_end = date(year, month, last_day)
    next_month_start = month_end + timedelta(days=1)
    return month_start, month_end, next_month_start


def _month_range_dt(year: int, month: int) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` datetimes (UTC) for the given month."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    _, last_day = monthrange(year, month)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from the GitHub API."""
    if not ts:
        return None
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# Changelog extraction
# ---------------------------------------------------------------------------

def _extract_changelog(body: str | None) -> str | None:
    """Return the contents of a ````` ```changelog ````` fence, or ``None``."""
    if not body:
        return None
    m = _CHANGELOG_RE.search(body)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# API-based per-repo helpers
# ---------------------------------------------------------------------------

def _fetch_merged_prs(
    client: httpx.Client,
    owner: str,
    repo: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Return search-result dicts for PRs merged in ``[start_date, end_date]``.

    Uses the Search API: one request (plus pagination if >100 results).
    ``start_date`` and ``end_date`` are ISO date strings (``YYYY-MM-DD``).
    """
    q = f"repo:{owner}/{repo} is:pr is:merged merged:{start_date}..{end_date}"
    params = {"q": q, "sort": "created", "per_page": str(_PER_PAGE)}
    return _search_paginate(client, params)


def _fetch_pr_body(
    client: httpx.Client,
    owner: str,
    repo: str,
    number: int,
) -> str:
    """Fetch the full body of a single PR via the pulls endpoint."""
    data = _get_json(client, f"/repos/{owner}/{repo}/pulls/{number}")
    return data.get("body") or ""


def _fetch_releases(
    client: httpx.Client,
    owner: str,
    repo: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return releases published within ``[start, end]`` (1 API call)."""
    all_releases: list[dict] = _get_json(  # type: ignore[assignment]
        client, f"/repos/{owner}/{repo}/releases", {"per_page": str(_PER_PAGE)},
    )
    if not isinstance(all_releases, list):
        return []
    filtered: list[dict] = []
    for rel in all_releases:
        pub = _parse_iso(rel.get("published_at"))
        if pub and start <= pub <= end:
            filtered.append(rel)
    return filtered


def _fetch_open_issues_count(
    client: httpx.Client,
    owner: str,
    repo: str,
) -> int:
    """Return the current ``open_issues_count`` for a repository (1 API call)."""
    data = _get_json(client, f"/repos/{owner}/{repo}")
    return int(data.get("open_issues_count", 0))


# ---------------------------------------------------------------------------
# Per-repo orchestration
# ---------------------------------------------------------------------------

def _collect_one_repo(
    client: httpx.Client,
    owner: str,
    repo: str,
    project_name: str,
    slug: str,
    year: int,
    month: int,
    cache_dir: Path,
) -> tuple[list[CollectedItem], RepoStats]:
    """Collect all data for a single repository."""
    items: list[CollectedItem] = []
    month_start, _month_end, next_month_start = _month_boundaries(year, month)
    dt_start, dt_end = _month_range_dt(year, month)

    # -- git dates ----------------------------------------------------------
    # git --after is exclusive, so use the day before month_start
    git_after = (month_start - timedelta(days=1)).isoformat()
    git_before = next_month_start.isoformat()

    # -- Git-based data (zero API calls) ------------------------------------
    repo_dir: Path | None = None
    commit_count = 0
    active_contributors: set[str] = set()
    new_contributors: set[str] = set()

    try:
        repo_dir = _ensure_bare_clone(owner, repo, cache_dir)
        default_branch = _resolve_default_branch(repo_dir)
        logger.info("    Default branch: %s", default_branch)

        commit_count = _git_commit_count(
            repo_dir, default_branch, git_after, git_before,
        )
        logger.info("    Commits (git): %d", commit_count)

        active_contributors = _git_active_contributors(
            repo_dir, default_branch, git_after, git_before,
        )
        logger.info("    Active contributors (git): %d", len(active_contributors))

        historical = _git_historical_contributors(
            repo_dir, default_branch, month_start.isoformat(),
        )
        new_contributors = active_contributors - historical
        if new_contributors:
            logger.info(
                "    New contributors: %s", ", ".join(sorted(new_contributors)),
            )
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.warning(
            "Git operations failed for %s — skipping git-based stats: %s",
            slug, exc,
        )

    # -- API-based data (minimal calls) -------------------------------------
    # Merged PRs via search API
    search_start = month_start.isoformat()
    search_end = _month_end.isoformat()
    merged_prs: list[dict] = []
    try:
        merged_prs = _fetch_merged_prs(client, owner, repo, search_start, search_end)
    except httpx.HTTPStatusError as exc:
        logger.warning("Failed to fetch merged PRs for %s: %s", slug, exc)
    logger.info("    Merged PRs: %d", len(merged_prs))

    for pr in merged_prs:
        author = (pr.get("user") or {}).get("login", "")
        pr_number: int = pr.get("number", 0)

        body: str = pr.get("body") or ""
        # Search results may truncate the body; fetch full body if needed
        if body and _CHANGELOG_RE.search(body):
            changelog = _extract_changelog(body)
        elif not body:
            try:
                body = _fetch_pr_body(client, owner, repo, pr_number)
            except httpx.HTTPStatusError:
                logger.debug("    Could not fetch body for PR #%d", pr_number)
                body = ""
            changelog = _extract_changelog(body)
        else:
            changelog = None

        # Derive the canonical merged_at timestamp
        merged_at_raw = pr.get("pull_request", {}).get("merged_at") or pr.get("closed_at")

        items.append(
            CollectedItem(
                source_repo=slug,
                project_name=project_name,
                title=pr.get("title", ""),
                url=pr.get("html_url", ""),
                kind="pr",
                number=pr_number,
                merged_at=merged_at_raw,
                author=author,
                description=body,
                changelog_body=changelog,
            ),
        )

    # Releases
    releases: list[dict] = []
    try:
        releases = _fetch_releases(client, owner, repo, dt_start, dt_end)
    except httpx.HTTPStatusError as exc:
        logger.warning("Failed to fetch releases for %s: %s", slug, exc)
    logger.info("    Releases: %d", len(releases))

    for rel in releases:
        author = (rel.get("author") or {}).get("login", "")
        items.append(
            CollectedItem(
                source_repo=slug,
                project_name=project_name,
                title=rel.get("name") or rel.get("tag_name", ""),
                url=rel.get("html_url", ""),
                kind="release",
                number=0,
                author=author,
                description=rel.get("body") or "",
            ),
        )

    # Open issues count
    open_issues = 0
    try:
        open_issues = _fetch_open_issues_count(client, owner, repo)
    except httpx.HTTPStatusError as exc:
        logger.warning("Failed to fetch open issues for %s: %s", slug, exc)
    logger.info("    Open issues: %d", open_issues)

    # -- Assemble stats -----------------------------------------------------
    stats = RepoStats(
        repo_slug=slug,
        open_issues=open_issues,
        merged_prs=len(merged_prs),
        commits=commit_count,
        releases=len(releases),
        active_contributors=active_contributors,
        new_contributors=new_contributors,
    )

    return items, stats


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def collect_github(
    repos: list[dict],
    year: int,
    month: int,
    github_token: str | None = None,
    cache_dir: Path | None = None,
) -> tuple[list[CollectedItem], list[RepoStats]]:
    """Collect GitHub activity for *repos* in the given *month*/*year*.

    Parameters
    ----------
    repos:
        A list of dicts, each with ``"name"`` (human-readable) and ``"slug"``
        (``"owner/repo"``).
    year:
        The calendar year.
    month:
        The calendar month (1-12).
    github_token:
        A GitHub personal-access token.  Falls back to the ``GITHUB_TOKEN``
        environment variable when *None*.
    cache_dir:
        Directory to store bare git clones.  Defaults to
        ``/tmp/autoposter-repo-cache``.

    Returns
    -------
    tuple[list[CollectedItem], list[RepoStats]]
        All collected items and per-repo statistics.
    """
    token = github_token or os.environ.get("GITHUB_TOKEN")
    if not token:
        logger.warning(
            "No GITHUB_TOKEN provided — API requests will be unauthenticated "
            "(low rate-limit).",
        )

    resolved_cache = cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR
    resolved_cache.mkdir(parents=True, exist_ok=True)

    logger.info("Collecting GitHub data for %04d-%02d …", year, month)
    logger.info("Repo cache directory: %s", resolved_cache)

    all_items: list[CollectedItem] = []
    all_stats: list[RepoStats] = []

    client = _build_client(token)
    try:
        for repo_cfg in repos:
            name: str = repo_cfg["name"]
            slug: str = repo_cfg["slug"]
            owner, repo = slug.split("/", 1)
            logger.info("  → %s (%s)", name, slug)

            try:
                items, stats = _collect_one_repo(
                    client, owner, repo, name, slug, year, month, resolved_cache,
                )
                all_items.extend(items)
                all_stats.append(stats)
            except Exception:
                logger.warning(
                    "Failed to collect data for %s — skipping.", slug,
                    exc_info=True,
                )
    finally:
        client.close()

    logger.info(
        "GitHub collection complete: %d items, %d repo stats.",
        len(all_items),
        len(all_stats),
    )
    return all_items, all_stats
