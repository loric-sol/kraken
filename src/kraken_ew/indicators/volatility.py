"""Volatility engine: ATR, Bollinger Bands, volatility regime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower})


def add_volatility(
    df: pd.DataFrame, atr_period: int = 14, bb_params: tuple[int, float] = (20, 2.0)
) -> pd.DataFrame:
    out = df.copy()
    out["atr"] = atr(out, atr_period)
    bb = bollinger_bands(out["close"], *bb_params)
    out = pd.concat([out, bb], axis=1)
    out["bb_width_pct"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"] * 100
    return out


@dataclass
class VolatilityState:
    regime: Literal["low", "normal", "high"]
    atr_pct: float  # ATR as % of price
    bb_width_pct: float


def volatility_state(df: pd.DataFrame, atr_period: int = 14, bb_params: tuple[int, float] = (20, 2.0)) -> VolatilityState:
    """Classify the current volatility regime using ATR% relative to its own
    rolling history (percentile-based), so it's self-normalizing per pair."""
    enriched = add_volatility(df, atr_period, bb_params)
    enriched["atr_pct"] = enriched["atr"] / enriched["close"] * 100

    last = enriched.iloc[-1]
    history = enriched["atr_pct"].dropna()

    if len(history) < 20:
        regime: Literal["low", "normal", "high"] = "normal"
    else:
        pct_rank = (history < last["atr_pct"]).mean()
        if pct_rank < 0.33:
            regime = "low"
        elif pct_rank > 0.66:
            regime = "high"
        else:
            regime = "normal"

    return VolatilityState(regime=regime, atr_pct=last["atr_pct"], bb_width_pct=last["bb_width_pct"])
