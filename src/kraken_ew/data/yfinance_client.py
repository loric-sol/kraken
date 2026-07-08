"""Stock market data via yfinance — replaces kraken_rest.py for equities."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

# yfinance interval strings for our minute-based convention
_INTERVAL_MAP = {
    1: "1m", 2: "2m", 5: "5m", 15: "15m", 30: "30m",
    60: "1h", 90: "90m", 1440: "1d",
}

OHLCV_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def _yf_interval(interval_minutes: int) -> str:
    iv = _INTERVAL_MAP.get(interval_minutes)
    if not iv:
        raise ValueError(f"Unsupported interval {interval_minutes}m. Use: {list(_INTERVAL_MAP)}")
    return iv


def get_ohlcv(ticker: str, interval: int = 60, period: str | None = None) -> list[tuple]:
    """Fetch OHLCV bars for *ticker* at *interval* minutes.

    Returns a list of (ts_unix, open, high, low, close, volume) tuples
    compatible with ohlcv_store.upsert_ohlcv.

    period: yfinance period string ('1mo', '3mo', '6mo', '1y', '2y', '5y').
    Defaults: 1h → '1mo', 1d → '2y', others → '1mo'.
    """
    yf_iv = _yf_interval(interval)
    if period is None:
        period = "2y" if interval == 1440 else "1mo"

    tk = yf.Ticker(ticker)
    df = tk.history(period=period, interval=yf_iv, auto_adjust=True)
    if df.empty:
        return []

    df.index = df.index.tz_convert("UTC")
    rows = []
    for ts, row in df.iterrows():
        # ohlcv_store expects (time, open, high, low, close, vwap, volume, count)
        # yfinance has no vwap/count — fill with 0 so the schema is compatible
        rows.append((
            int(ts.timestamp()),
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
            0.0,              # vwap placeholder
            float(row["Volume"]),
            0,                # count placeholder
        ))
    return rows


def get_ticker_price(ticker: str) -> float:
    """Return the latest market price for *ticker*."""
    tk = yf.Ticker(ticker)
    info = tk.fast_info
    return float(info.last_price)


def get_options_chain(ticker: str, dte_min: int = 21, dte_max: int = 45) -> pd.DataFrame:
    """Fetch the options chain for *ticker*, filtered to expirations within
    [dte_min, dte_max] calendar days from today.

    Returns a combined calls+puts DataFrame with columns:
      expiry, dte, option_type, strike, lastPrice, bid, ask, mid,
      impliedVolatility, delta (placeholder), openInterest, volume, inTheMoney
    """
    tk = yf.Ticker(ticker)
    expirations = tk.options  # list of expiry strings 'YYYY-MM-DD'
    if not expirations:
        return pd.DataFrame()

    today = datetime.now(timezone.utc).date()
    frames = []
    for exp_str in expirations:
        exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp - today).days
        if not (dte_min <= dte <= dte_max):
            continue
        chain = tk.option_chain(exp_str)
        for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
            df = df.copy()
            df["expiry"] = exp_str
            df["dte"] = dte
            df["option_type"] = opt_type
            df["mid"] = (df["bid"] + df["ask"]) / 2
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    keep = ["expiry", "dte", "option_type", "strike", "lastPrice",
            "bid", "ask", "mid", "impliedVolatility", "openInterest",
            "volume", "inTheMoney"]
    return combined[[c for c in keep if c in combined.columns]]
