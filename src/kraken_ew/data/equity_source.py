"""Unified equity OHLCV fetch.

Massive Market Data is the sole trusted source: deep, clean, split-adjusted
history. yfinance was retired as a silent fallback because it produced
materially different (and less reliable) bars than Massive -- e.g. SHOP once
scored 63 *long* on yfinance vs 33 *short* on Massive for the same day. Silent
fallback to worse data can corrupt a score without anyone noticing, so:

  - source="auto"/"massive": require Massive. If the key is missing or the API
    errors, RAISE -- never quietly compute a score on bad data.
  - source="yfinance": explicit, deliberate opt-in only (e.g. offline testing).

Returns the same 8-column row format ohlcv_store.upsert_ohlcv consumes:
[time_seconds, open, high, low, close, vwap, volume, count].
"""

from __future__ import annotations

import time

from kraken_ew.data import massive_rest

# Default lookback (days) per interval when fetching from Massive.
_DEFAULT_LOOKBACK_DAYS = {1440: 730, 240: 180, 60: 45}


def _start_for(interval: int) -> str:
    days = _DEFAULT_LOOKBACK_DAYS.get(interval, 365)
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))


def fetch_equity_ohlcv(
    ticker: str,
    interval: int = 1440,
    source: str = "auto",
) -> tuple[list[list], str]:
    """Return (rows, source_used) for *ticker* at *interval* minutes.

    source: "auto"/"massive" -> Massive only (raises if unavailable);
            "yfinance" -> explicit opt-in to the retired fallback source.
    """
    if source == "yfinance":
        # Deliberate opt-in only. Imported lazily so the dependency is optional.
        from kraken_ew.data import yfinance_client
        return yfinance_client.get_ohlcv(ticker, interval=interval), "yfinance"

    if source not in ("auto", "massive"):
        raise ValueError(f"unknown source {source!r}; use 'auto', 'massive', or 'yfinance'")

    if not massive_rest.has_api_key():
        raise massive_rest.MassiveAPIError(
            "MASSIVE_API_KEY not set. Massive is the only trusted equity data "
            "source; refusing to silently fall back to yfinance. Set the key in "
            ".env, or pass source='yfinance' to deliberately use the retired source."
        )

    rows = massive_rest.get_equity_ohlc(ticker, interval=interval, start=_start_for(interval))
    if not rows:
        raise massive_rest.MassiveAPIError(
            f"Massive returned no bars for {ticker} @ {interval}m. Refusing to "
            "fall back to yfinance; check the ticker/interval or Massive status."
        )
    return rows, "massive"
