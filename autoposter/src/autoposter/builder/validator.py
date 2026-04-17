"""Validate a rendered blog post before opening a pull request.

Checks cover typographic dash usage, YAML frontmatter structure, URL
provenance, and chart-file existence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

__all__ = ["validate_post"]

log = logging.getLogger(__name__)

# Markdown link patterns
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Typographic dashes to reject
_BAD_DASHES = {
    "\u2014": "em dash",
    "\u2013": "en dash",
    "\u2015": "horizontal bar",
}


def validate_post(
    content: str,
    collected_urls: set[str],
    chart_dir: Path,
) -> list[str]:
    """Return validation errors for a rendered blog post.

    An empty list means the post is valid.

    Parameters
    ----------
    content:
        The full Markdown string to validate.
    collected_urls:
        Set of URLs that were legitimately collected during the pipeline
        run.  Every ``[text](url)`` link in *content* must appear in this
        set.
    chart_dir:
        Directory against which ``![alt](path)`` image references are
        resolved.

    Returns
    -------
    list[str]
        Human-readable error messages, one per problem found.
    """
    errors: list[str] = []

    _check_dashes(content, errors)
    _check_frontmatter(content, errors)
    _check_urls(content, collected_urls, errors)
    _check_charts(content, chart_dir, errors)

    if errors:
        log.warning("Post validation found %d error(s)", len(errors))
    else:
        log.info("Post validation passed")

    return errors


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_dashes(content: str, errors: list[str]) -> None:
    """Reject em dashes, en dashes, and horizontal bars."""
    for char, name in _BAD_DASHES.items():
        if char in content:
            errors.append(f"Content contains a {name} ({char!r}); use a regular hyphen instead")


def _check_frontmatter(content: str, errors: list[str]) -> None:
    """Validate YAML frontmatter structure."""
    if not content.startswith("---"):
        errors.append("Post does not start with YAML frontmatter ('---')")
        return

    parts = content.split("---", 2)
    # parts[0] is empty (before the first ---), parts[1] is the YAML block
    if len(parts) < 3:
        errors.append("YAML frontmatter is not properly closed with a second '---'")
        return

    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        errors.append(f"YAML frontmatter is not valid YAML: {exc}")
        return

    if not isinstance(fm, dict):
        errors.append("YAML frontmatter does not contain a mapping")
        return

    for required_key in ("title", "layout"):
        if required_key not in fm:
            errors.append(f"YAML frontmatter is missing required key '{required_key}'")


def _check_urls(content: str, collected_urls: set[str], errors: list[str]) -> None:
    """Ensure every Markdown link URL was collected during the pipeline."""
    for match in _LINK_RE.finditer(content):
        # Skip image links (handled by _check_charts)
        if match.start() > 0 and content[match.start() - 1] == "!":
            continue
        url = match.group(2)
        if url not in collected_urls:
            errors.append(f"URL not in collected set: {url}")


def _check_charts(content: str, chart_dir: Path, errors: list[str]) -> None:
    """Ensure every referenced chart image exists on disk."""
    for match in _IMAGE_RE.finditer(content):
        img_path = match.group(2)
        resolved = chart_dir / img_path
        if not resolved.exists():
            errors.append(f"Referenced chart file does not exist: {img_path} (resolved to {resolved})")
