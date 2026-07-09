import numpy as np
import pandas as pd
import pytest

from kraken_ew.config import load_momentum_strategy_config
from kraken_ew.indicators import momentum
from kraken_ew.scoring.momentum_strategy import compute_momentum_score


def _df_from_close(close: np.ndarray) -> pd.DataFrame:
    n = len(close)
    ts = np.arange(n) * 3600
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        }
    )


@pytest.fixture
def accelerating_uptrend_df() -> pd.DataFrame:
    """Price compounding upward (exponential growth) -- momentum (MACD
    histogram magnitude) keeps growing bar over bar, unlike a linear or
    decelerating-convex rise where the histogram settles toward a constant."""
    n = 80
    close = 100 * (1.02 ** np.arange(n))
    return _df_from_close(close)


@pytest.fixture
def stalling_uptrend_df() -> pd.DataFrame:
    """A steep rise (pushes RSI into overbought) that flattens out over the
    back half -- momentum should be exhausting even though price is still
    elevated."""
    n = 80
    steep = 100 + np.arange(50) * 3.0
    flat = steep[-1] + np.arange(1, n - 49) * 0.05
    close = np.concatenate([steep, flat])
    return _df_from_close(close)


def test_detect_momentum_regime_expansion(accelerating_uptrend_df):
    regime = momentum.detect_momentum_regime(accelerating_uptrend_df, lookback=10)
    assert regime.state == "expansion"
    assert regime.strength > 0


def test_detect_momentum_regime_exhaustion(stalling_uptrend_df):
    regime = momentum.detect_momentum_regime(stalling_uptrend_df, lookback=10)
    assert regime.state == "exhaustion"
    assert regime.strength > 0


def test_detect_momentum_regime_neutral_needs_lookback(uptrend_df):
    short = uptrend_df.iloc[:5]
    regime = momentum.detect_momentum_regime(short, lookback=10)
    assert regime.state == "neutral"
    assert regime.strength == 0.0


def test_compute_momentum_score_uptrend(uptrend_df):
    config = load_momentum_strategy_config()
    breakdown = compute_momentum_score(uptrend_df, "TESTUSD", config)
    assert 0 <= breakdown.total <= 100
    assert set(breakdown.components) == set(config.weights)
    assert set(breakdown.weighted) == set(config.weights)
    assert breakdown.direction == "long"
    assert abs(sum(breakdown.weighted.values()) - breakdown.total) < 1e-9


def test_compute_momentum_score_downtrend(downtrend_df):
    config = load_momentum_strategy_config()
    breakdown = compute_momentum_score(downtrend_df, "TESTUSD", config)
    assert breakdown.direction == "short"
    assert 0 <= breakdown.total <= 100


def test_momentum_weights_sum_to_one():
    config = load_momentum_strategy_config()
    assert abs(sum(config.weights.values()) - 1.0) < 1e-6
