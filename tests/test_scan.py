import numpy as np
import pandas as pd

from kraken_ew.dashboard.scan import MOMENTUM_SCREEN_MIN_TIMEFRAMES, _momentum_screen


def _strong_uptrend_df(n: int = 100) -> pd.DataFrame:
    # A brief dip then a strong climb -- RSI genuinely rising into the high
    # 60s/70s on the last bar (not pinned at a saturated 100, which a
    # perfectly linear uptrend would produce and which can't be "rising"
    # bar-over-bar since it's already at the ceiling).
    close = np.concatenate([100 - np.arange(20) * 0.3, 94 + np.arange(n - 20) * 1.0])
    return pd.DataFrame(
        {
            "ts": np.arange(n) * 3600,
            "open": close - 0.2, "high": close + 0.5, "low": close - 0.5,
            "close": close, "volume": np.full(n, 1000.0),
        }
    )


def _flat_df(n: int = 100) -> pd.DataFrame:
    close = 100 + np.sin(np.arange(n) * 0.01) * 0.01
    return pd.DataFrame(
        {
            "ts": np.arange(n) * 3600,
            "open": close, "high": close + 0.01, "low": close - 0.01,
            "close": close, "volume": np.full(n, 1000.0),
        }
    )


def test_momentum_screen_bullish_hit_ignores_wave_direction():
    """4H + 1H strongly bullish, 1D neutral -> 2-of-3 -> bullish hit.
    Never touches compute_score/ScoreBreakdown.direction -- confirms the
    screen is wave-independent (this is the exact MORPHO case: strong 4H/1H
    RSI with the composite `direction` mislabeled "short" by a broken wave
    count should still surface here)."""
    df_d = _flat_df()
    df_4h = _strong_uptrend_df()
    df_1h = _strong_uptrend_df()

    hit, detail = _momentum_screen(df_d, df_4h, df_1h)

    assert hit == "bullish"
    assert "4H:bullish" in detail
    assert "1H:bullish" in detail


def test_momentum_screen_no_hit_when_only_one_timeframe_bullish():
    df_d = _flat_df()
    df_4h = _flat_df()
    df_1h = _strong_uptrend_df()

    hit, _ = _momentum_screen(df_d, df_4h, df_1h)

    assert hit == ""


def test_momentum_screen_min_timeframes_constant_is_two():
    # Guards the "2-of-3" rule the test above assumes.
    assert MOMENTUM_SCREEN_MIN_TIMEFRAMES == 2
