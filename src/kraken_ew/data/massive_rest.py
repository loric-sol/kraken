"""Thin client for the Massive Market Data REST API.

Massive provides deep historical OHLC aggregates (up to 50,000 bars per
request over an arbitrary date range), which removes Kraken's ~720-candle
cap -- see data/fetch_history.py for why that cap matters. We use Massive as
the *backtest* data source (deep daily + intraday history) while keeping
Kraken for live/recent scoring.

Auth: set MASSIVE_API_KEY in the environment (see .env.example). The endpoint
paths are Polygon-compatible, so the API key is passed as the `apiKey` query
parameter. Crypto tickers use the `X:` prefix, e.g. `X:BTCUSD`.

Docs: https://massive.com (Custom Bars / Aggregates endpoint)
"""

from __future__ import annotations

import os
import time

import requests

BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")

# Map our Kraken altnames -> Massive crypto tickers. Massive uses ISO-ish
# currency codes with an X: prefix for crypto, so XBT -> BTC and XDG -> DOGE.
_KRAKEN_TO_MASSIVE = {
    "XBTUSD": "X:BTCUSD",
    "ETHUSD": "X:ETHUSD",
    "SOLUSD": "X:SOLUSD",
    "AVAXUSD": "X:AVAXUSD",
    "XDGUSD": "X:DOGEUSD",
}


class MassiveAPIError(RuntimeError):
    pass


def massive_ticker(kraken_pair: str) -> str:
    """Translate a Kraken altname (e.g. 'XBTUSD') to a Massive crypto ticker
    (e.g. 'X:BTCUSD'). Falls back to prefixing 'X:' for unmapped pairs."""
    if kraken_pair in _KRAKEN_TO_MASSIVE:
        return _KRAKEN_TO_MASSIVE[kraken_pair]
    if kraken_pair.startswith("X:"):
        return kraken_pair
    return f"X:{kraken_pair}"


def _api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise MassiveAPIError(
            "MASSIVE_API_KEY not set. Export it or pass api_key=... "
            "(see .env.example)."
        )
    return key


def _get(path: str, params: dict, api_key: str | None, retries: int = 6, backoff: float = 1.0) -> dict:
    url = f"{BASE_URL}{path}"
    params = {**params, "apiKey": _api_key(api_key)}
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            # 429 = plan rate limit (Massive free tier is ~5 req/min). Wait out
            # the window rather than burning retries on short exponential backoff.
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 13))
                last_exc = MassiveAPIError(f"429 rate-limited on {path}")
                if attempt < retries - 1:
                    time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status not in (None, "OK", "DELAYED"):
                raise MassiveAPIError(f"{path} returned status={status}: {data.get('error')}")
            return data
        except (requests.RequestException, MassiveAPIError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    raise MassiveAPIError(f"failed to fetch {path} after {retries} attempts") from last_exc


# Massive timespan strings keyed by the interval (in minutes) we use elsewhere.
_INTERVAL_TO_TIMESPAN = {
    1: (1, "minute"),
    5: (5, "minute"),
    15: (15, "minute"),
    60: (1, "hour"),
    240: (4, "hour"),
    1440: (1, "day"),
}


def get_ohlc(
    pair: str,
    interval: int = 1440,
    start: str = "2024-01-01",
    end: str | None = None,
    api_key: str | None = None,
    limit: int = 50000,
) -> list[list]:
    """Fetch OHLC candles for `pair` over [start, end] at `interval` minutes.

    `pair` may be a Kraken altname ('XBTUSD') or a Massive ticker ('X:BTCUSD').
    `start`/`end` are YYYY-MM-DD strings; `end` defaults to today.

    Returns rows in the SAME format Kraken's client uses, so
    ohlcv_store.upsert_ohlcv consumes them unchanged:
        [time_seconds, open, high, low, close, vwap, volume, count]
    """
    if interval not in _INTERVAL_TO_TIMESPAN:
        raise MassiveAPIError(
            f"unsupported interval {interval}; choose one of {sorted(_INTERVAL_TO_TIMESPAN)}"
        )
    multiplier, timespan = _INTERVAL_TO_TIMESPAN[interval]
    ticker = massive_ticker(pair)
    end = end or time.strftime("%Y-%m-%d", time.gmtime())

    path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}"
    data = _get(path, {"sort": "asc", "limit": limit}, api_key)

    return _parse_bars(data.get("results") or [])


def _parse_bars(results: list[dict]) -> list[list]:
    """Convert Massive/Polygon bars into the 8-column row format that
    ohlcv_store.upsert_ohlcv consumes:
        [time_seconds, open, high, low, close, vwap, volume, count]
    """
    rows: list[list] = []
    for bar in results:
        # Massive bar: o,h,l,c (prices), v (volume), vw (vwap), t (ms), n (trades)
        ts_seconds = int(bar["t"] // 1000)
        rows.append(
            [
                ts_seconds,
                float(bar["o"]),
                float(bar["h"]),
                float(bar["l"]),
                float(bar["c"]),
                float(bar.get("vw", bar["c"])),
                float(bar.get("v", 0.0)),
                int(bar.get("n", 0)),
            ]
        )
    return rows


def get_equity_ohlc(
    ticker: str,
    interval: int = 1440,
    start: str = "2024-01-01",
    end: str | None = None,
    api_key: str | None = None,
    limit: int = 50000,
) -> list[list]:
    """Fetch OHLC candles for an EQUITY `ticker` (bare symbol, e.g. 'GOOGL' —
    no 'X:' prefix). Split-adjusted. Returns the same 8-column row format as
    get_ohlc so ohlcv_store.upsert_ohlcv consumes it unchanged.
    """
    if interval not in _INTERVAL_TO_TIMESPAN:
        raise MassiveAPIError(
            f"unsupported interval {interval}; choose one of {sorted(_INTERVAL_TO_TIMESPAN)}"
        )
    multiplier, timespan = _INTERVAL_TO_TIMESPAN[interval]
    end = end or time.strftime("%Y-%m-%d", time.gmtime())

    path = f"/v2/aggs/ticker/{ticker.upper()}/range/{multiplier}/{timespan}/{start}/{end}"
    data = _get(path, {"sort": "asc", "limit": limit, "adjusted": "true"}, api_key)
    return _parse_bars(data.get("results") or [])


def has_api_key(api_key: str | None = None) -> bool:
    """True if a Massive API key is available (env or passed)."""
    return bool(api_key or os.environ.get("MASSIVE_API_KEY"))
