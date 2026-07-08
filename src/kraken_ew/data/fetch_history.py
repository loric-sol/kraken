"""Backfill historical OHLCV data into DuckDB from one of two sources.

Two data sources are supported (both emit the same row format, so the DuckDB
store consumes them identically):

1. Kraken (source="kraken", default) -- public, no API key. LIMITATION:
   Kraken's /OHLC endpoint always returns only the most recent ~720 candles
   regardless of the `since` parameter, so history depth is interval-bound:
     - interval=60   (1h)  -> ~30 days
     - interval=1440 (1d)  -> ~2 years
   Good for recent/live scoring; statistically thin for backtesting.

2. Massive (source="massive") -- requires MASSIVE_API_KEY (see .env.example).
   Returns up to 50,000 bars over an ARBITRARY date range, removing the cap.
   This is the source to use for statistically meaningful backtests (deep
   daily AND intraday history). See data/massive_rest.py.

Usage:
    python -m kraken_ew.data.fetch_history --pair XBTUSD --interval 1440
    python -m kraken_ew.data.fetch_history --pair XBTUSD --interval 60 \
        --source massive --start 2023-01-01
"""

from __future__ import annotations

from kraken_ew.data import kraken_rest, massive_rest, ohlcv_store


def backfill(pair: str, interval: int = 60, db_path=None) -> int:
    """Fetch the available history (up to Kraken's ~720-candle cap) for `pair`
    at `interval` minutes and store in DuckDB. Returns rows inserted."""
    con = ohlcv_store.connect(db_path) if db_path else ohlcv_store.connect()
    rows, _ = kraken_rest.get_ohlc(pair, interval=interval)
    return ohlcv_store.upsert_ohlcv(con, pair, interval, rows)


def backfill_massive(
    pair: str,
    interval: int = 1440,
    start: str = "2023-01-01",
    end: str | None = None,
    db_path=None,
    api_key: str | None = None,
) -> int:
    """Fetch deep history for `pair` at `interval` minutes from Massive over
    [start, end] and store in DuckDB under the Kraken altname `pair` (so the
    rest of the pipeline keys on it unchanged). Returns rows inserted."""
    con = ohlcv_store.connect(db_path) if db_path else ohlcv_store.connect()
    rows = massive_rest.get_ohlc(pair, interval=interval, start=start, end=end, api_key=api_key)
    return ohlcv_store.upsert_ohlcv(con, pair, interval, rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", required=True, help="Kraken altname, e.g. XBTUSD")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--source", choices=["kraken", "massive"], default="kraken")
    parser.add_argument("--start", default="2023-01-01", help="(massive) YYYY-MM-DD start date")
    parser.add_argument("--end", default=None, help="(massive) YYYY-MM-DD end date; defaults to today")
    args = parser.parse_args()

    if args.source == "massive":
        n = backfill_massive(args.pair, interval=args.interval, start=args.start, end=args.end)
    else:
        n = backfill(args.pair, interval=args.interval)
    print(f"Inserted {n} new rows for {args.pair} @ {args.interval}m from {args.source}")
