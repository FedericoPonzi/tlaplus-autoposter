"""Collector for the TLA+ Google Group mailing list archive.

Scrapes the `MHonArc <https://www.mhonarc.org/>`_-generated archive at
``discuss.tlapl.us`` to extract discussion threads from a target month.
Individual message pages are fetched to determine dates; binary search is
used to minimise HTTP requests.

HTML structure assumptions
--------------------------
The **date index** (``maillist.html``) is a flat ``<ul>`` of ``<li>``
elements, each containing an ``<a>`` tag with ``name`` (message number)
and ``href`` (relative link to the message page) attributes::

    <li>
      <strong>
        <a name="06742" href="msg06742.html">Re: [tlaplus] Subject</a>
      </strong>
      <ul><li><em>From</em>: Author Name</li></ul>
    </li>

Each **individual message page** stores the date in an HTML comment::

    <!--X-Date: Thu, 16 Apr 2026 19:35:30 +0200 -->

and in the visible header::

    <li><em>Date</em>: Thu, 16 Apr 2026 10:35:11 -0700</li>
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from autoposter.models import CommunityThread

__all__ = ["collect_google_group"]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subject normalisation
# ---------------------------------------------------------------------------

# Strip "Re:", "[tlaplus]", "Fwd:", etc. from subjects for thread grouping.
# Handles nested/repeated prefixes such as "Re: [tlaplus] Re: Fwd: …".
_RE_SUBJECT_PREFIX = re.compile(
    r"^(?:\s*(?:Re|Fwd)\s*:\s*)*(?:\[tlaplus\]\s*)?(?:(?:Re|Fwd)\s*:\s*)*",
    re.IGNORECASE,
)

# MHonArc <!--X-Date: …--> HTML comment.
_RE_XDATE = re.compile(r"<!--X-Date:\s*(.+?)\s*-->")


def _normalize_subject(subject: str) -> str:
    """Strip mailing-list prefixes to produce a canonical thread subject."""
    return _RE_SUBJECT_PREFIX.sub("", subject).strip()


# ---------------------------------------------------------------------------
# Internal data
# ---------------------------------------------------------------------------


@dataclass
class _MessageEntry:
    """A single message parsed from the MHonArc date-index page."""

    msg_num: int
    subject: str
    href: str  # e.g. "msg06742.html"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _fetch_page(url: str) -> str | None:
    """Download *url* and return the response text, or ``None`` on error."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        log.warning("Failed to fetch %s", url, exc_info=True)
        return None


def _client_fetch(client: httpx.Client, url: str) -> str | None:
    """Fetch *url* using an existing :class:`httpx.Client`."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        log.debug("Failed to fetch %s", url, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Mail-index parsing
# ---------------------------------------------------------------------------


def _parse_mail_index(html: str) -> list[_MessageEntry]:
    """Parse the MHonArc date-index page into message entries.

    Returns entries sorted by message number **ascending** (oldest first).
    """
    soup = BeautifulSoup(html, "lxml")
    entries: list[_MessageEntry] = []

    # Assumed structure: <a name="NNNNN" href="msgNNNNN.html">Subject</a>
    for anchor in soup.find_all("a", attrs={"name": True, "href": True}):
        name = anchor.get("name", "")
        href = anchor.get("href", "")
        if not name or not href:
            continue
        try:
            msg_num = int(name)
        except ValueError:
            continue

        subject = anchor.get_text(strip=True)
        if not subject:
            continue

        entries.append(_MessageEntry(msg_num=msg_num, subject=subject, href=href))

    entries.sort(key=lambda e: e.msg_num)
    return entries


# ---------------------------------------------------------------------------
# Date extraction from individual message pages
# ---------------------------------------------------------------------------


def _parse_message_date(html: str) -> datetime | None:
    """Extract the date from a single MHonArc message page.

    Tries two strategies:

    1. The ``<!--X-Date: …-->`` HTML comment (most reliable).
    2. The ``<li><em>Date</em>: …</li>`` element in the message header.
    """
    # Strategy 1: X-Date HTML comment
    m = _RE_XDATE.search(html)
    if m:
        try:
            dt = parsedate_to_datetime(m.group(1))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            log.debug("Failed to parse X-Date comment: %s", m.group(1))

    # Strategy 2: visible Date field in the message header list
    soup = BeautifulSoup(html, "lxml")
    for li in soup.find_all("li"):
        em = li.find("em")
        if em and em.get_text(strip=True).lower() == "date":
            full_text = li.get_text(strip=True)
            date_text = re.sub(r"^Date\s*:\s*", "", full_text, flags=re.IGNORECASE)
            try:
                dt = parsedate_to_datetime(date_text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                log.debug("Failed to parse Date field: %s", date_text)

    return None


def _get_message_date(
    client: httpx.Client,
    entry: _MessageEntry,
    base_url: str,
    cache: dict[int, datetime],
) -> datetime | None:
    """Return the date for *entry*, fetching and caching as needed."""
    if entry.msg_num in cache:
        return cache[entry.msg_num]

    url = urljoin(base_url, entry.href)
    html = _client_fetch(client, url)
    if html is None:
        return None

    dt = _parse_message_date(html)
    if dt is not None:
        cache[entry.msg_num] = dt
    else:
        log.warning("Could not extract date from %s", url)
    return dt


# ---------------------------------------------------------------------------
# Binary search for month boundaries
# ---------------------------------------------------------------------------


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` UTC datetimes bounding the given month.

    *start* is midnight on the 1st; *end* is midnight on the 1st of the
    **next** month (exclusive upper bound).
    """
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _find_month_messages(
    client: httpx.Client,
    entries: list[_MessageEntry],
    base_url: str,
    year: int,
    month: int,
) -> tuple[list[_MessageEntry], dict[int, datetime]]:
    """Identify messages from the target month using binary search.

    Messages are assumed to be roughly ordered by date (newer messages
    have higher message numbers).  Binary search finds approximate
    boundaries and the results are verified at the edges.

    Returns ``(filtered_entries, date_cache)``.
    """
    if not entries:
        return [], {}

    month_start, month_end = _month_bounds(year, month)
    cache: dict[int, datetime] = {}

    def fetch_date(idx: int) -> datetime | None:
        return _get_message_date(client, entries[idx], base_url, cache)

    # --- Lower bound: first entry with date >= month_start ----------------
    lo, hi = 0, len(entries) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        dt = fetch_date(mid)
        if dt is None:
            # Cannot determine date; skip rightward.
            lo = mid + 1
            continue
        if dt < month_start:
            lo = mid + 1
        else:
            hi = mid
    start_idx = lo

    # Quick check: does this entry actually fall within the month?
    start_dt = fetch_date(start_idx)
    if start_dt is None or start_dt >= month_end:
        log.debug("Binary search: no messages found for %04d-%02d", year, month)
        return [], cache

    # --- Upper bound: last entry with date < month_end --------------------
    lo, hi = start_idx, len(entries) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2  # bias high to avoid infinite loop
        dt = fetch_date(mid)
        if dt is None:
            hi = mid - 1
            continue
        if dt < month_end:
            lo = mid
        else:
            hi = mid - 1
    end_idx = lo

    # --- Boundary refinement ----------------------------------------------
    # Message ordering may not be perfectly monotone, so verify a small
    # window around each boundary and adjust if needed.
    margin = 5
    refined_start = start_idx
    for idx in range(max(0, start_idx - margin), start_idx):
        dt = fetch_date(idx)
        if dt is not None and month_start <= dt < month_end:
            refined_start = min(refined_start, idx)

    refined_end = end_idx
    for idx in range(end_idx + 1, min(len(entries), end_idx + margin + 1)):
        dt = fetch_date(idx)
        if dt is not None and month_start <= dt < month_end:
            refined_end = max(refined_end, idx)

    month_entries = entries[refined_start : refined_end + 1]
    return month_entries, cache


# ---------------------------------------------------------------------------
# Thread grouping
# ---------------------------------------------------------------------------


def _build_threads(
    entries: list[_MessageEntry],
    base_url: str,
    date_cache: dict[int, datetime],
    year: int,
    month: int,
    client: httpx.Client,
) -> list[CommunityThread]:
    """Group *entries* by subject and build :class:`CommunityThread` objects.

    Parameters
    ----------
    entries:
        Messages from the target month, sorted by ``msg_num`` ascending.
    base_url:
        Base URL used to resolve relative message hrefs.
    date_cache:
        Pre-populated ``{msg_num: datetime}`` cache (from the boundary
        search).  Entries not already cached are fetched on demand.
    year, month:
        Target year/month, used only as a fallback date.
    client:
        HTTP client for fetching message pages (date extraction).
    """
    # Group by normalised subject.
    groups: dict[str, list[_MessageEntry]] = {}
    for entry in entries:
        key = _normalize_subject(entry.subject)
        groups.setdefault(key, []).append(entry)

    for msgs in groups.values():
        msgs.sort(key=lambda e: e.msg_num)

    threads: list[CommunityThread] = []
    for subject, msgs in sorted(groups.items()):
        first = msgs[0]
        reply_count = len(msgs) - 1

        # Resolve the date of the earliest message in this thread.
        dt = _get_message_date(client, first, base_url, date_cache)
        if dt is not None:
            date_str = dt.strftime("%Y-%m-%d")
        else:
            date_str = f"{year:04d}-{month:02d}-01"
            log.warning(
                "Using fallback date for thread %r (could not fetch date)", subject,
            )

        threads.append(
            CommunityThread(
                subject=subject,
                url=urljoin(base_url, first.href),
                reply_count=reply_count,
                date=date_str,
                is_notable=reply_count > 2,
            ),
        )

    return threads


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_google_group(
    archive_url: str,
    year: int,
    month: int,
) -> tuple[list[CommunityThread], int]:
    """Collect discussion threads from the TLA+ Google Group for a given month.

    Fetches the MHonArc date-index page, uses binary search to locate the
    target month's messages, and groups them into threads.

    Parameters
    ----------
    archive_url:
        URL of the MHonArc date-index page, e.g.
        ``https://discuss.tlapl.us/maillist.html``.
    year:
        Target year (e.g. ``2025``).
    month:
        Target month (``1``–``12``).

    Returns
    -------
    tuple[list[CommunityThread], int]
        ``(threads, total_message_count)`` where *threads* is one
        :class:`CommunityThread` per discussion topic and
        *total_message_count* is the sum of all messages (original +
        replies) across those threads.
    """
    html = _fetch_page(archive_url)
    if html is None:
        return [], 0

    entries = _parse_mail_index(html)
    if not entries:
        log.warning("No messages found in date index at %s", archive_url)
        return [], 0

    log.info("Parsed %d message entries from the date index", len(entries))
    base_url = archive_url.rsplit("/", 1)[0] + "/"

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        month_entries, date_cache = _find_month_messages(
            client, entries, base_url, year, month,
        )

        if not month_entries:
            log.info("No messages found for %04d-%02d", year, month)
            return [], 0

        log.info("Found %d messages in %04d-%02d", len(month_entries), year, month)

        threads = _build_threads(
            month_entries, base_url, date_cache, year, month, client,
        )

    total_messages = sum(t.reply_count + 1 for t in threads)
    log.info(
        "Collected %d threads, %d total messages for %04d-%02d",
        len(threads),
        total_messages,
        year,
        month,
    )
    return threads, total_messages
