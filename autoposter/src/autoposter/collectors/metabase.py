"""Collector for tool-run telemetry from the public Metabase dashboard.

Queries the public dashboard API at ``metabase.tlapl.us`` to fetch TLC
execution counts per month.  The dashboard UUID is extracted from the
configured URL automatically.

The API works as follows:

1. ``GET /api/public/dashboard/{uuid}`` returns dashboard metadata
   including dashcard IDs, card IDs, and parameter definitions.
2. ``GET /api/public/dashboard/{uuid}/dashcard/{dc}/card/{c}?parameters=JSON``
   returns the actual data for a specific card on the dashboard.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from autoposter.models import ToolRunStats

__all__ = ["collect_metabase"]

log = logging.getLogger(__name__)

_API_BASE = "https://metabase.tlapl.us/api/public"
_REQUEST_TIMEOUT = 30.0

# Card names we look for when auto-discovering from the dashboard.
_TARGET_CARD_NAMES = ("exec stats per month", "execution description per month")

_DASHBOARD_UUID_RE = re.compile(r"/public/dashboard/([0-9a-f-]{36})")

# IDs of the dashboard filter parameters that exclude automated/bot runs.
_AUTOMATION_PARAM_ID = "a63dfe69"
_CATEGORY_PARAM_ID = "f200d4ab"


def collect_metabase(
    dashboard_url: str,
    card_uuids: list[str],
    year: int,
    month: int,
) -> ToolRunStats:
    """Fetch tool-run counts from the Metabase public dashboard.

    Parameters
    ----------
    dashboard_url:
        Full URL of the public Metabase dashboard.
    card_uuids:
        Unused (kept for config compatibility). The collector now queries
        the dashboard directly.
    year:
        Target year.
    month:
        Target month (1-12).

    Returns
    -------
    ToolRunStats
        TLC run count for the target month. Returns zeroes on failure.
    """
    dash_uuid = _extract_dashboard_uuid(dashboard_url)
    if not dash_uuid:
        log.warning("Could not extract dashboard UUID from URL: %s", dashboard_url)
        return ToolRunStats()

    log.info("Fetching Metabase dashboard %s", dash_uuid)

    dashboard = _fetch_dashboard(dash_uuid)
    if dashboard is None:
        return ToolRunStats()

    dashcards = dashboard.get("dashcards", [])
    params = dashboard.get("parameters", [])

    target = _find_target_dashcard(dashcards)
    if target is None:
        log.warning(
            "Could not find per-month stats card. Available: %s",
            [dc.get("card", {}).get("name") for dc in dashcards],
        )
        return ToolRunStats()

    dashcard_id = target["id"]
    card_id = target["card"]["id"]
    log.info(
        "Found target card: '%s' (dashcard=%d, card=%d)",
        target["card"].get("name"),
        dashcard_id,
        card_id,
    )

    # Build default parameters (automation exclusion filters).
    default_params = _build_default_params(params)

    # Fetch total TLC runs for the target month.
    tlc_runs = _fetch_monthly_count(
        dash_uuid, dashcard_id, card_id, default_params, year, month,
    )

    log.info("Metabase result for %04d-%02d: TLC runs=%d", year, month, tlc_runs)
    return ToolRunStats(tlc_runs=tlc_runs, apalache_runs=0)


def _extract_dashboard_uuid(url: str) -> str | None:
    m = _DASHBOARD_UUID_RE.search(url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Dashboard metadata
# ---------------------------------------------------------------------------


def _fetch_dashboard(dash_uuid: str) -> dict[str, Any] | None:
    """Fetch dashboard metadata (cards, parameters, etc.)."""
    try:
        resp = httpx.get(
            f"{_API_BASE}/dashboard/{dash_uuid}",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Failed to fetch Metabase dashboard: %s", exc)
        return None


def _find_target_dashcard(dashcards: list[dict]) -> dict | None:
    """Find the dashcard with per-month execution stats."""
    for dc in dashcards:
        card = dc.get("card") or {}
        name = (card.get("name") or "").lower()
        if any(t in name for t in _TARGET_CARD_NAMES):
            return dc

    # Fallback: bar/line chart with "exec" or "month" in the name.
    for dc in dashcards:
        card = dc.get("card") or {}
        display = card.get("display", "")
        name = (card.get("name") or "").lower()
        if display in ("bar", "line") and ("exec" in name or "month" in name):
            return dc

    return None


def _build_default_params(params: list[dict]) -> list[dict]:
    """Extract default parameter values from the dashboard definition."""
    result = []
    for p in params:
        default = p.get("default")
        if default is not None:
            result.append({"id": p["id"], "type": p.get("type", "category"), "value": default})
    return result


# ---------------------------------------------------------------------------
# Card data query
# ---------------------------------------------------------------------------


def _query_card(
    dash_uuid: str,
    dashcard_id: int,
    card_id: int,
    params: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Query a dashboard card via the public dashboard card-query endpoint.

    ``GET /api/public/dashboard/{uuid}/dashcard/{dc}/card/{c}?parameters=JSON``
    """
    url = f"{_API_BASE}/dashboard/{dash_uuid}/dashcard/{dashcard_id}/card/{card_id}"
    query_params: dict[str, str] = {}
    if params:
        query_params["parameters"] = json.dumps(params)

    log.debug("GET %s params=%s", url, list(query_params.keys()))

    try:
        resp = httpx.get(url, params=query_params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        log.warning("Card query returned HTTP %s", exc.response.status_code)
    except (httpx.RequestError, ValueError) as exc:
        log.warning("Card query failed: %s", exc)

    return None


def _fetch_monthly_count(
    dash_uuid: str,
    dashcard_id: int,
    card_id: int,
    default_params: list[dict],
    year: int,
    month: int,
) -> int:
    """Fetch total execution count for the target month.

    Queries the card without category filtering (gets combined TLC count)
    and extracts the row matching the target year/month.
    """
    # Query without params first (uses dashboard defaults).
    payload = _query_card(dash_uuid, dashcard_id, card_id)
    if payload is None:
        # Retry with explicit default params.
        payload = _query_card(dash_uuid, dashcard_id, card_id, default_params)
    if payload is None:
        return 0

    return _extract_month_count(payload, year, month)


def _extract_month_count(payload: dict[str, Any], year: int, month: int) -> int:
    """Extract the count for the target month from a card response.

    Expected response shape::

        {"data": {"cols": [{"name": "execution_timestamp"}, {"name": "count"}],
                  "rows": [["2026-03-01T00:00:00+01:00", 209261], ...]}}
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        log.warning("Unexpected Metabase payload (no 'data' key)")
        return 0

    cols = data.get("cols", [])
    rows = data.get("rows", [])

    if not cols or not rows:
        log.warning("Empty Metabase response (no cols/rows)")
        return 0

    # Find the date and count columns.
    col_names = [(c.get("name") or "").lower() for c in cols]
    date_idx = _find_date_column(col_names)
    count_idx = _find_count_column(col_names)

    if count_idx is None:
        log.warning("No count column found in: %s", col_names)
        return 0

    target = f"{year:04d}-{month:02d}"

    for row in rows:
        if date_idx is not None:
            val = str(row[date_idx]).strip()
            if not val.startswith(target):
                continue
        try:
            return int(row[count_idx])
        except (TypeError, ValueError, IndexError):
            continue

    log.info("No data found for %s in %d rows", target, len(rows))
    return 0


def _find_date_column(col_names: list[str]) -> int | None:
    date_hints = ("timestamp", "month", "date", "period", "time")
    for idx, name in enumerate(col_names):
        if any(hint in name for hint in date_hints):
            return idx
    return None


def _find_count_column(col_names: list[str]) -> int | None:
    count_hints = ("count", "total", "runs", "executions", "number")
    for idx, name in enumerate(col_names):
        if any(hint in name for hint in count_hints):
            return idx
    # If only 2 columns and one is a date, the other is the count.
    if len(col_names) == 2:
        date_idx = _find_date_column(col_names)
        if date_idx is not None:
            return 1 - date_idx
    return None
