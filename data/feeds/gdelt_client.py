"""
data/feeds/gdelt_client.py

GDELT Doc 2.0 API client — structured conflict event ingestion.

Uses the gdeltdoc library when available; falls back to the raw urllib-based
implementation when the library is not installed.

Public API:
    fetch_gdelt_articles(queries, timespan, max_records) → list[dict]
    score_gdelt_articles(articles)                       → float (0-100)
    get_gdelt_raw()                                      → dict  (legacy shape for conflict_index)
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ── Query sets ────────────────────────────────────────────────────────────────
# Three short, focused queries — each covers one distinct conflict zone.
# GDELT treats spaces as AND; keep ≤5 terms per query to avoid zero results.
# GDELT_SLEEP seconds between queries prevents HTTP 429.

GDELT_QUERIES: list[str] = [
    "Iran Israel military airstrike",
    "Ukraine Russia war invasion",
    "Venezuela cartel military violence",
]
GDELT_SLEEP = 3.5          # seconds between queries
GDELT_API   = "https://api.gdeltproject.org/api/v2/doc/doc"


# ── Core fetch ────────────────────────────────────────────────────────────────

def fetch_gdelt_articles(
    queries:     list[str] | None = None,
    timespan:    str = "3d",
    max_records: int = 75,
) -> list[dict]:
    """
    Query GDELT DOC 2.0 and return a flat list of article dicts.

    Each article dict has (at minimum):
      url, title, seendate, socialimage, domain, language, sourcecountry

    Returns [] on failure (caller degrades gracefully).
    """
    queries = queries or GDELT_QUERIES
    articles: list[dict] = []

    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(GDELT_SLEEP)

        params = urllib.parse.urlencode({
            "query":      query,
            "mode":       "artlist",
            "maxrecords": str(max_records),
            "timespan":   timespan,
            "sort":       "toneasc",
            "format":     "json",
        })
        url = f"{GDELT_API}?{params}"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Arca-OSINT/2.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            batch = data.get("articles", [])
            logger.info(f"GDELT [{i+1}/{len(queries)}] '{query}': {len(batch)} articles")
            for art in batch:
                art["_query"] = query          # tag source query
            articles.extend(batch)

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                logger.warning(f"GDELT [{i+1}] HTTP 429 — sleeping extra 10s")
                time.sleep(10.0)
            else:
                logger.warning(f"GDELT [{i+1}] HTTP {exc.code}")
        except Exception as exc:
            logger.warning(f"GDELT [{i+1}] failed: {exc}")

    return articles


def score_gdelt_articles(articles: list[dict]) -> float:
    """
    Convert article list to 0-100 conflict score.
    Gate: ≥15 articles required. Saturates at 67 articles (100 pts).
    """
    n = len(articles)
    if n < 15:
        return 0.0
    return round(min(100.0, n * 1.5), 1)


# ── Legacy shape (conflict_index backward compatibility) ──────────────────────

def get_gdelt_raw() -> dict:
    """
    Return the legacy dict shape consumed by conflict_index._score_gdelt().

      {"articles": int, "source": str}
    """
    articles = fetch_gdelt_articles()
    n = len(articles)
    if n == 0:
        source = "gdelt_no_data"
    else:
        source = "gdelt_ok"
    return {"articles": n, "source": source}
