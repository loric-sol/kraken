"""Bridge script: score a ticker from externally-supplied OHLCV bars (e.g.
fetched live via the Robinhood MCP) without needing a Python-callable data
client. Reads JSON from stdin:

{"ticker": "SPY", "bars": [{"ts": 1750000000, "open":.., "high":.., "low":.., "close":.., "volume":..}, ...]}

Writes the ScoreBreakdown as JSON to stdout.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from kraken_ew.config import load_scoring_config
from kraken_ew.scoring.composite import compute_score


def main() -> None:
    payload = json.load(sys.stdin)
    ticker = payload["ticker"]
    bars = payload["bars"]

    df = pd.DataFrame(bars)
    df = df.sort_values("ts").reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["ts"], unit="s", utc=True)

    config = load_scoring_config()
    breakdown = compute_score(df, ticker, config)

    out = {
        "ticker": ticker,
        "total": breakdown.total,
        "direction": breakdown.direction,
        "components": breakdown.components,
        "weighted": breakdown.weighted,
        "metadata": breakdown.metadata,
        "last_close": float(df["close"].iloc[-1]),
        "bars_used": len(df),
    }
    json.dump(out, sys.stdout, default=str)


if __name__ == "__main__":
    main()
