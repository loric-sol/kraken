from kraken_ew.indicators import momentum, trend, volatility, volume


def test_trend_state_uptrend(uptrend_df):
    state = trend.trend_state(uptrend_df, periods=(5, 10, 20))
    assert state.direction == "up"
    assert state.ema_fast > state.ema_mid > state.ema_slow
    assert 0 <= state.strength <= 100


def test_trend_state_downtrend(downtrend_df):
    state = trend.trend_state(downtrend_df, periods=(5, 10, 20))
    assert state.direction == "down"
    assert state.ema_fast < state.ema_mid < state.ema_slow


def test_trend_score_range(uptrend_df):
    score = trend.trend_score(uptrend_df, periods=(5, 10, 20))
    assert 0 <= score <= 100


def test_rsi_uptrend_above_50(uptrend_df):
    rsi = momentum.rsi(uptrend_df["close"])
    assert rsi.iloc[-1] > 50


def test_rsi_downtrend_below_50(downtrend_df):
    rsi = momentum.rsi(downtrend_df["close"])
    assert rsi.iloc[-1] < 50


def test_momentum_score_long_in_uptrend(uptrend_df):
    score = momentum.momentum_score(uptrend_df, direction="long")
    assert 0 <= score <= 100
    assert score > 50  # uptrend should favor a long momentum score


def test_atr_positive(uptrend_df):
    a = volatility.atr(uptrend_df)
    assert (a.dropna() > 0).all()


def test_volatility_state(uptrend_df):
    state = volatility.volatility_state(uptrend_df)
    assert state.regime in ("low", "normal", "high")
    assert state.atr_pct > 0


def test_volume_score_long_above_vwap(uptrend_df):
    score = volume.volume_score(uptrend_df, direction="long")
    assert 0 <= score <= 100
    # price rising steadily -> above VWAP and OBV rising -> should score high
    assert score > 50
