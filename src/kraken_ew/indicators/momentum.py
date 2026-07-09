"""Momentum engine: RSI, MACD, StochRSI, divergence detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # avg_loss == 0: pure gains -> RSI 100; both 0 (no movement yet/at all) -> 50.
    out = out.where(avg_loss != 0, np.where(avg_gain > 0, 100.0, 50.0))
    return pd.Series(out, index=close.index).fillna(50.0)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def stoch_rsi(close: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> pd.DataFrame:
    r = rsi(close, period)
    lowest = r.rolling(period).min()
    highest = r.rolling(period).max()
    raw_k = ((r - lowest) / (highest - lowest).replace(0, np.nan)) * 100
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return pd.DataFrame({"stoch_k": k.fillna(50.0), "stoch_d": d.fillna(50.0)})


def add_momentum(
    df: pd.DataFrame,
    rsi_period: int = 14,
    macd_params: tuple[int, int, int] = (12, 26, 9),
    stoch_period: int = 14,
) -> pd.DataFrame:
    out = df.copy()
    out["rsi"] = rsi(out["close"], rsi_period)
    macd_df = macd(out["close"], *macd_params)
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["signal"]
    out["macd_hist"] = macd_df["hist"]
    stoch_df = stoch_rsi(out["close"], stoch_period)
    out["stoch_k"] = stoch_df["stoch_k"]
    out["stoch_d"] = stoch_df["stoch_d"]
    return out


@dataclass
class Divergence:
    kind: Literal["bullish", "bearish", "none"]
    strength: float  # 0-100


def detect_divergence(df: pd.DataFrame, lookback: int = 20) -> Divergence:
    """Compare price swing vs RSI swing over `lookback` bars to find
    regular divergence at the most recent local extreme.

    Bullish: price makes a lower low but RSI makes a higher low.
    Bearish: price makes a higher high but RSI makes a lower high.
    """
    enriched = add_momentum(df) if "rsi" not in df.columns else df
    window = enriched.tail(lookback)
    if len(window) < lookback:
        return Divergence("none", 0.0)

    price = window["close"]
    rsi_vals = window["rsi"]

    # Split window into two halves, compare extremes of each half.
    mid = lookback // 2
    first, second = window.iloc[:mid], window.iloc[mid:]

    price_low_change = second["close"].min() - first["close"].min()
    rsi_low_change = second["rsi"].min() - first["rsi"].min()
    price_high_change = second["close"].max() - first["close"].max()
    rsi_high_change = second["rsi"].max() - first["rsi"].max()

    if price_low_change < 0 and rsi_low_change > 0:
        strength = min(100.0, abs(rsi_low_change) * 5)
        return Divergence("bullish", strength)

    if price_high_change > 0 and rsi_high_change < 0:
        strength = min(100.0, abs(rsi_high_change) * 5)
        return Divergence("bearish", strength)

    return Divergence("none", 0.0)


@dataclass
class MomentumRegime:
    state: Literal["expansion", "exhaustion", "neutral"]
    strength: float  # 0-100


def detect_momentum_regime(df: pd.DataFrame, lookback: int = 10) -> MomentumRegime:
    """Classify momentum as expanding, exhausting, or neutral over the last
    `lookback` bars.

    - Expansion: |MACD histogram| is growing and RSI is moving away from 50
      -- momentum is accelerating, a continuation signal.
    - Exhaustion: RSI is in overbought/oversold territory (>70 or <30) while
      |MACD histogram| is shrinking -- price is still extended but the
      momentum behind it is fading, a classic reversal warning.
    """
    enriched = add_momentum(df) if "macd_hist" not in df.columns else df
    window = enriched.tail(lookback)
    if len(window) < lookback:
        return MomentumRegime("neutral", 0.0)

    hist_abs = window["macd_hist"].abs()
    hist_slope = hist_abs.iloc[-1] - hist_abs.iloc[0]
    rsi_last = window["rsi"].iloc[-1]
    rsi_dist_from_mid = abs(rsi_last - 50)

    if (rsi_last > 70 or rsi_last < 30) and hist_slope < 0:
        strength = min(100.0, abs(hist_slope) * 20 + max(0.0, rsi_dist_from_mid - 20))
        return MomentumRegime("exhaustion", float(np.clip(strength, 0, 100)))

    if hist_slope > 0 and rsi_dist_from_mid > 10:
        strength = min(100.0, hist_slope * 20 + rsi_dist_from_mid)
        return MomentumRegime("expansion", float(np.clip(strength, 0, 100)))

    return MomentumRegime("neutral", 0.0)


def momentum_score(df: pd.DataFrame, direction: Literal["long", "short"]) -> float:
    """0-100 score for the "momentum confirmation" composite component,
    given a candidate trade direction. Combines RSI/MACD/StochRSI alignment
    with `direction` plus any divergence in `direction`'s favor."""
    enriched = add_momentum(df)
    last = enriched.iloc[-1]
    score = 0.0

    if direction == "long":
        score += 40 * np.clip((last["rsi"] - 30) / 40, 0, 1)
        score += 30 if last["macd_hist"] > 0 else 0
        score += 30 * np.clip(last["stoch_k"] / 100, 0, 1)
    else:
        score += 40 * np.clip((70 - last["rsi"]) / 40, 0, 1)
        score += 30 if last["macd_hist"] < 0 else 0
        score += 30 * np.clip((100 - last["stoch_k"]) / 100, 0, 1)

    div = detect_divergence(enriched)
    if (direction == "long" and div.kind == "bullish") or (direction == "short" and div.kind == "bearish"):
        score = min(100.0, score + div.strength * 0.3)

    return float(np.clip(score, 0, 100))
