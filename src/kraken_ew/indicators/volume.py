"""Volume engine: VWAP, OBV, volume confirmation."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def rolling_vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Rolling VWAP over `window` bars (typical price * volume / volume)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical_price * df["volume"]
    return pv.rolling(window).sum() / df["volume"].rolling(window).sum()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def add_volume(df: pd.DataFrame, vwap_window: int = 20) -> pd.DataFrame:
    out = df.copy()
    out["vwap"] = rolling_vwap(out, vwap_window)
    out["obv"] = obv(out)
    return out


def volume_score(df: pd.DataFrame, direction: Literal["long", "short"], lookback: int = 10) -> float:
    """0-100 score for the "volume confirmation" composite component.

    Combines:
      - price vs VWAP alignment with `direction`
      - OBV trend (rising for long, falling for short) over `lookback` bars
    """
    enriched = add_volume(df)
    last = enriched.iloc[-1]
    score = 0.0

    if pd.notna(last["vwap"]):
        if direction == "long" and last["close"] > last["vwap"]:
            score += 50
        elif direction == "short" and last["close"] < last["vwap"]:
            score += 50

    obv_window = enriched["obv"].tail(lookback)
    if len(obv_window) >= 2:
        obv_change = obv_window.iloc[-1] - obv_window.iloc[0]
        if direction == "long" and obv_change > 0:
            score += 50
        elif direction == "short" and obv_change < 0:
            score += 50

    return float(np.clip(score, 0, 100))
