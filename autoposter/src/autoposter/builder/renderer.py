"""Render a monthly TLA+ blog post from summarized data and a Jinja2 template.

This module loads the ``post.md.j2`` template, injects summarized data, and
writes the final Markdown file to disk.
"""

from __future__ import annotations

import logging
from pathlib import Path

import jinja2

from autoposter.config import Config
from autoposter.models import SummarizedData

__all__ = ["render_post", "write_post"]

log = logging.getLogger(__name__)

def _get_template_dir() -> Path:
    from autoposter import PROJECT_ROOT
    return PROJECT_ROOT / "templates"


def render_post(
    summarized: SummarizedData,
    config: Config,
    chart_paths: list[Path],
) -> str:
    """Render the monthly blog post Markdown from *summarized* data.

    Parameters
    ----------
    summarized:
        Output of the Summarize stage containing intro text, development
        update bullets, community bullets, and metrics.
    config:
        Resolved pipeline configuration (provides month/year helpers).
    chart_paths:
        Paths to generated chart images (currently unused by the template
        directly, but available for future extensions).

    Returns
    -------
    str
        The fully-rendered Markdown string.
    """
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_get_template_dir())),
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    template = env.get_template("post.md.j2")

    rendered = template.render(
        intro=summarized.intro,
        dev_updates=summarized.dev_update_bullets,
        metrics=summarized.metrics,
        community_items=summarized.community_bullets,
        month_name=config.month_name,
        year=config.year,
        month_padded=config.month_padded,
    )

    log.info("Rendered post (%d characters)", len(rendered))
    return rendered


def write_post(content: str, output_dir: Path, year: int, month: int) -> Path:
    """Write the rendered post to disk.

    The file is written as ``{output_dir}/{year}-{month:02d}-dev-update.md``.
    The output directory is created if it does not already exist.

    Parameters
    ----------
    content:
        Rendered Markdown string.
    output_dir:
        Directory in which to write the post file.
    year:
        Target year (e.g. 2026).
    month:
        Target month (1--12).

    Returns
    -------
    Path
        Absolute path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{year}-{month:02d}-dev-update.md"
    path = output_dir / filename
    path.write_text(content)

    log.info("Wrote post to %s", path)
    return path
