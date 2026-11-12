"""Bot 1's news filter (Nov 12 2026 test, /mnt/project-files/reports/bot-tests-nov12.md).

Skip an opening-range breakout when the stock has had no headline of its own since the previous trading
day's 4pm ET close. A headline is "its own" when Alpaca's news feed tags it with at most 2 symbols, so
market-wide stories don't count. In the 3-year test the quiet-day trades lost money in both the first two
years (PF 0.91) and the unseen last year (PF 0.66); skipping them lifted the unseen year from PF 1.23 to 1.32.

Turned on with NEWS_FILTER=1. If the news feed can't be reached the trade is allowed (fail open), so an outage
never silently stops the bot.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
URL = "https://data.alpaca.markets/v1beta1/news"
log = logging.getLogger("news")
_seen: dict[tuple[str, date], bool] = {}  # (symbol, day) -> found its own headline (only positives are cached)


def window_start(now_et: datetime) -> datetime:
    """4pm ET on the previous weekday."""
    d = now_et.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, time(16, 0), ET)


def own_headlines(articles: list[dict], symbol: str, max_symbols: int = 2) -> list[str]:
    return [a.get("headline", "") for a in articles
            if symbol in a.get("symbols", []) and len(a.get("symbols", [])) <= max_symbols]


def fetch(symbol: str, start: datetime, end: datetime, key: str, secret: str) -> list[dict]:
    q = (f"?symbols={symbol}&start={start.astimezone(ZoneInfo('UTC')):%Y-%m-%dT%H:%M:%SZ}"
         f"&end={end.astimezone(ZoneInfo('UTC')):%Y-%m-%dT%H:%M:%SZ}&limit=50&include_content=false")
    req = urllib.request.Request(URL + q, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("news", [])


def has_news(symbol: str, now_et: datetime, key: str, secret: str, fetcher=fetch) -> bool:
    """True if `symbol` had a headline of its own since the last close (or the feed failed)."""
    k = (symbol, now_et.date())
    if _seen.get(k):
        return True
    try:
        found = own_headlines(fetcher(symbol, window_start(now_et), now_et, key, secret), symbol)
    except Exception as e:  # noqa: BLE001
        log.warning("News check for %s failed (%s); allowing the trade", symbol, e)
        return True
    if found:
        _seen[k] = True
        log.info("%s news since the last close: %s", symbol, found[0][:100])
    return bool(found)
