"""Publisher that creates a git branch, commits the rendered post, and opens a draft PR.

Orchestrates the final pipeline stage: branch creation, file staging, commit,
push, and draft pull-request via the GitHub REST API (``httpx``).
"""

from __future__ import annotations

import calendar
import logging
import subprocess
from pathlib import Path

import httpx

__all__ = [
    "create_branch",
    "commit_post",
    "open_draft_pr",
    "publish",
]

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], repo_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command inside *repo_dir* and return the result.

    Raises
    ------
    subprocess.CalledProcessError
        If the command exits with a non-zero status.
    """
    cmd = ["git", *args]
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), repo_dir)
    return subprocess.run(
        cmd,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )


def _month_name(month: int) -> str:
    """Return the full English month name for *month* (1–12)."""
    return calendar.month_name[month]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def create_branch(year: int, month: int, repo_dir: Path) -> str:
    """Create and switch to a new branch for the monthly update.

    Parameters
    ----------
    year:
        Four-digit year (e.g. 2025).
    month:
        Month number (1–12).
    repo_dir:
        Path to the local git repository.

    Returns
    -------
    str
        The branch name, e.g. ``devupdate/2025-06``.
    """
    branch = f"devupdate/{year}-{month:02d}"
    logger.info("Creating branch %s", branch)
    _run_git(["checkout", "-b", branch], repo_dir)
    return branch


def commit_post(
    post_path: Path,
    asset_paths: list[Path],
    repo_dir: Path,
    year: int,
    month: int,
) -> str:
    """Stage the post and assets, then create a commit.

    Parameters
    ----------
    post_path:
        Path to the rendered blog-post file (e.g. a ``.md`` file).
    asset_paths:
        Paths to any accompanying asset files (images, charts, etc.).
    repo_dir:
        Path to the local git repository.
    year:
        Four-digit year for the commit message.
    month:
        Month number (1–12) for the commit message.

    Returns
    -------
    str
        The full SHA of the newly created commit.
    """
    files_to_stage = [str(post_path), *(str(p) for p in asset_paths)]
    logger.info("Staging %d file(s)", len(files_to_stage))
    _run_git(["add", "--", *files_to_stage], repo_dir)

    message = f"{_month_name(month)} {year} development update"
    logger.info("Committing: %s", message)
    _run_git(["commit", "-m", message], repo_dir)

    result = _run_git(["rev-parse", "HEAD"], repo_dir)
    sha = result.stdout.strip()
    logger.info("Commit SHA: %s", sha)
    return sha


def open_draft_pr(
    branch: str,
    target_repo: str,
    year: int,
    month: int,
    contributors: list[str],
    github_token: str,
) -> str:
    """Open a draft pull request on *target_repo* via the GitHub REST API.

    Parameters
    ----------
    branch:
        The head branch name (e.g. ``devupdate/2025-06``).
    target_repo:
        GitHub ``owner/repo`` slug where the PR should be opened.
    year:
        Four-digit year for the PR title.
    month:
        Month number (1–12) for the PR title.
    contributors:
        GitHub usernames to @-mention in the PR body.
    github_token:
        Personal access token (or fine-grained token) with ``repo`` scope.

    Returns
    -------
    str
        The URL of the newly created pull request.

    Raises
    ------
    httpx.HTTPStatusError
        If the GitHub API returns a non-2xx response.
    """
    title = f"{_month_name(month)} {year} Development Update"

    mention_lines = "\n".join(f"- @{c}" for c in contributors)
    body = (
        f"## {title}\n\n"
        "Auto-generated monthly development update.\n\n"
        "### Contributors\n\n"
        f"{mention_lines}\n"
    )

    url = f"{_GITHUB_API}/repos/{target_repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title,
        "head": branch,
        "base": "main",
        "body": body,
        "draft": True,
    }

    logger.info("Opening draft PR on %s: %s", target_repo, title)
    response = httpx.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    pr_url: str = response.json()["html_url"]
    logger.info("Draft PR created: %s", pr_url)
    return pr_url


def publish(
    post_path: Path,
    asset_paths: list[Path],
    target_repo: str,
    year: int,
    month: int,
    contributors: list[str],
    github_token: str,
    repo_dir: Path,
) -> str:
    """Orchestrate the full publish flow: branch → commit → push → draft PR.

    Parameters
    ----------
    post_path:
        Path to the rendered blog-post file.
    asset_paths:
        Paths to any accompanying asset files.
    target_repo:
        GitHub ``owner/repo`` slug for the PR.
    year:
        Four-digit year.
    month:
        Month number (1–12).
    contributors:
        GitHub usernames to @-mention.
    github_token:
        GitHub API token.
    repo_dir:
        Path to the local git repository.

    Returns
    -------
    str
        The URL of the newly created draft pull request.
    """
    branch = create_branch(year, month, repo_dir)
    commit_post(post_path, asset_paths, repo_dir, year, month)

    logger.info("Pushing branch %s to origin", branch)
    _run_git(["push", "--set-upstream", "origin", branch], repo_dir)

    pr_url = open_draft_pr(
        branch=branch,
        target_repo=target_repo,
        year=year,
        month=month,
        contributors=contributors,
        github_token=github_token,
    )
    return pr_url
