import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def uptrend_df() -> pd.DataFrame:
    """A clean, steadily rising synthetic OHLCV series (100 bars)."""
    n = 100
    ts = np.arange(n) * 3600
    close = 100 + np.arange(n) * 1.0
    high = close + 0.5
    low = close - 0.5
    open_ = close - 0.2
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def downtrend_df() -> pd.DataFrame:
    """A clean, steadily falling synthetic OHLCV series (100 bars)."""
    n = 100
    ts = np.arange(n) * 3600
    close = 200 - np.arange(n) * 1.0
    high = close + 0.5
    low = close - 0.5
    open_ = close + 0.2
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def zigzag_df() -> pd.DataFrame:
    """A synthetic price series with clear, large alternating swings,
    suitable for ZigZag pivot detection with a 5% threshold."""
    segments = [100, 130, 110, 150, 120, 170, 140, 190]
    prices = []
    for a, b in zip(segments, segments[1:]):
        prices.extend(np.linspace(a, b, 10, endpoint=False))
    prices.append(segments[-1])
    prices = np.array(prices)
    n = len(prices)
    ts = np.arange(n) * 3600
    high = prices + 0.1
    low = prices - 0.1
    open_ = prices
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": prices, "volume": volume}
    )
