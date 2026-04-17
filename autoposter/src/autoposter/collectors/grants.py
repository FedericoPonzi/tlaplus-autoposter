"""Collector for TLA+ Foundation grants page.

Scrapes the grants listing at foundation.tlapl.us and returns structured
:class:`GrantInfo` objects for each grant entry found.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from autoposter.models import GrantInfo

__all__ = ["collect_grants"]

log = logging.getLogger(__name__)


def collect_grants(
    grants_url: str,
) -> list[GrantInfo]:
    """Fetch the TLA+ Foundation grants page and extract grant listings.

    The function scrapes the *main* grants index page, which uses the Hugo
    Relearn theme's ``children`` shortcode to render child-page summaries.
    Each child page is rendered as an ``<h2>`` with a link, followed by a
    ``<p>`` containing its description.

    Parameters
    ----------
    grants_url:
        Full URL of the grants index page, e.g.
        ``https://foundation.tlapl.us/grants/index.html``.

    Returns
    -------
    list[GrantInfo]
        One entry per grant listing found on the page.  The list may be empty
        if the page structure has changed or the fetch fails.
    """
    html = _fetch_page(grants_url)
    if html is None:
        return []
    return _parse_grants(html, grants_url)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_page(url: str) -> str | None:
    """Download *url* and return the response body, or ``None`` on error."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        log.warning("Failed to fetch grants page at %s", url, exc_info=True)
        return None


def _parse_grants(html: str, base_url: str) -> list[GrantInfo]:
    """Extract grant listings from the raw HTML of the grants index page."""
    soup = BeautifulSoup(html, "lxml")

    # --- Strategy 1: Hugo Relearn "children" shortcode -----------------------
    # The grants index page renders child pages inside a <div> whose class
    # list includes "children".  Each child is an <h2 class="children-title">
    # containing an <a> link, followed by a sibling <p> with the description.
    children_div = soup.find("div", class_="children")
    if isinstance(children_div, Tag):
        grants = _extract_from_children_div(children_div, base_url)
        if grants:
            log.info("Collected %d grant listing(s) via children div", len(grants))
            return grants
        log.warning("Found children div but could not extract any grants")

    # --- Strategy 2: fall back to <article> h2/h3 headings ------------------
    # If the page layout changes, try to find grant-like headings inside the
    # main <article> element.
    article = soup.find("article")
    if isinstance(article, Tag):
        grants = _extract_from_headings(article, base_url)
        if grants:
            log.info(
                "Collected %d grant listing(s) via article headings", len(grants)
            )
            return grants

    log.warning(
        "Could not find any grant listings on %s — the page structure may have changed",
        base_url,
    )
    return []


def _extract_from_children_div(div: Tag, base_url: str) -> list[GrantInfo]:
    """Parse grants from the Hugo Relearn ``children`` shortcode markup.

    Expected HTML structure (may change)::

        <div class="children children-h2 ...">
          <h2 class="children-title" id="...">
            <a href="/grants/2024-grant-program/index.html">Title</a>
          </h2>
          <p>Description text…</p>
          ...
        </div>
    """
    grants: list[GrantInfo] = []

    # Each child entry is an <h2 class="children-title">.
    headings = div.find_all("h2", class_="children-title")
    for heading in headings:
        if not isinstance(heading, Tag):
            continue

        # --- title & URL from the <a> inside the heading --------------------
        link = heading.find("a", href=True)
        if not isinstance(link, Tag):
            log.warning("Grant heading has no link: %s", heading.get_text(strip=True))
            title = heading.get_text(strip=True)
            url = base_url
        else:
            title = link.get_text(strip=True)
            url = urljoin(base_url, str(link["href"]))

        # --- description from the next sibling <p> -------------------------
        description = ""
        next_sib = heading.find_next_sibling()
        if isinstance(next_sib, Tag) and next_sib.name == "p":
            description = next_sib.get_text(strip=True)
        else:
            log.warning("No <p> description found after heading '%s'", title)

        grants.append(GrantInfo(title=title, url=url, description=description))

    return grants


def _extract_from_headings(article: Tag, base_url: str) -> list[GrantInfo]:
    """Fallback: extract grants from ``<h2>``/``<h3>`` headings in *article*.

    This handles a potential future layout where individual grants appear
    directly as headings (with or without anchor links) followed by ``<p>``
    description paragraphs — similar to the grant-recipients sub-page.
    """
    grants: list[GrantInfo] = []

    for heading in article.find_all(["h2", "h3"]):
        if not isinstance(heading, Tag):
            continue

        # Skip the page's own <h1>-equivalent title if it leaked into h2.
        heading_id = heading.get("id", "")
        if heading_id in ("tla-foundation-grants", "tla-foundation-grant-recipients"):
            continue

        link = heading.find("a", href=True)
        if isinstance(link, Tag):
            title = link.get_text(strip=True)
            url = urljoin(base_url, str(link["href"]))
        else:
            title = heading.get_text(strip=True)
            # Construct a fragment URL from the heading's id attribute.
            if heading_id:
                url = f"{base_url}#{heading_id}"
            else:
                url = base_url

        if not title:
            continue

        # Collect consecutive <p> siblings as the description.
        paragraphs: list[str] = []
        for sib in heading.find_next_siblings():
            if not isinstance(sib, Tag):
                continue
            if sib.name == "p":
                paragraphs.append(sib.get_text(strip=True))
            else:
                break  # stop at the next non-<p> element

        description = " ".join(paragraphs)
        grants.append(GrantInfo(title=title, url=url, description=description))

    return grants
