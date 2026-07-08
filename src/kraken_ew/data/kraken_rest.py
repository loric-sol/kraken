"""Thin client for Kraken's public REST API (no API key required).

Docs: https://docs.kraken.com/api/docs/rest-api/get-ohlc-data
"""

from __future__ import annotations

import time

import requests

BASE_URL = "https://api.kraken.com/0/public"

# OHLC response columns, per Kraken docs.
OHLC_COLUMNS = ["time", "open", "high", "low", "close", "vwap", "volume", "count"]


class KrakenAPIError(RuntimeError):
    pass


def _get(endpoint: str, params: dict, retries: int = 3, backoff: float = 1.0) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise KrakenAPIError(f"{endpoint} error: {data['error']}")
            return data["result"]
        except (requests.RequestException, KrakenAPIError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    raise KrakenAPIError(f"failed to fetch {endpoint} after {retries} attempts") from last_exc


def get_ohlc(pair: str, interval: int = 60, since: int | None = None) -> tuple[list[list], int]:
    """Fetch OHLC candles for `pair` (Kraken altname, e.g. 'XBTUSD').

    Returns (rows, last) where rows is a list of
    [time, open, high, low, close, vwap, volume, count] and `last` is the
    timestamp to pass as `since` for the next page.
    """
    params = {"pair": pair, "interval": interval}
    if since is not None:
        params["since"] = since
    result = _get("OHLC", params)
    last = int(result.pop("last"))
    # result has one remaining key: the pair's altname (sometimes differs in case)
    rows = next(iter(result.values()))
    return rows, last


def get_ticker(pair: str) -> dict:
    result = _get("Ticker", {"pair": pair})
    return next(iter(result.values()))


def get_asset_pairs() -> dict:
    return _get("AssetPairs", {})
