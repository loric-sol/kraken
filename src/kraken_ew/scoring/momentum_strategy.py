"""Standalone momentum-engine strategy: a scored strategy parallel to the
Elliott Wave composite (scoring/composite.py), built purely from the
momentum/trend/volume/volatility engines -- no wave counting or Fibonacci
confluence.

This exists so the falsification comparison in backtest/run_backtest.py has
a *quantified, scored* momentum strategy to test EW against, not just the
crude single-indicator RSI-cross baseline in backtest/baselines.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from kraken_ew.config import MomentumStrategyConfig
from kraken_ew.indicators import momentum as momentum_mod
from kraken_ew.indicators import trend as trend_mod
from kraken_ew.indicators import volatility as volatility_mod
from kraken_ew.indicators import volume as volume_mod

Direction = Literal["long", "short"]

_VOLATILITY_REGIME_SCORE = {"low": 20.0, "normal": 60.0, "high": 100.0}


@dataclass
class MomentumScoreBreakdown:
    total: float
    components: dict[str, float]
    weighted: dict[str, float]
    direction: Direction
    regime: str
    metadata: dict = field(default_factory=dict)


def _direction(df: pd.DataFrame, ema_periods: tuple[int, int, int]) -> Direction:
    """No wave count to imply direction here, so use the EMA trend stack,
    falling back to MACD sign when the stack is mixed (sideways)."""
    state = trend_mod.trend_state(df, periods=ema_periods)
    if state.direction == "up":
        return "long"
    if state.direction == "down":
        return "short"
    macd_df = momentum_mod.macd(df["close"])
    return "long" if macd_df["macd"].iloc[-1] >= 0 else "short"


def compute_momentum_score(df: pd.DataFrame, pair: str, config: MomentumStrategyConfig) -> MomentumScoreBreakdown:
    """Run the momentum/trend/volume/volatility engines on `df` and combine
    them per `config.weights` into a 0-100 composite score with a full
    breakdown for the decision log."""
    weights = config.weights
    ema_periods = tuple(config.indicators["ema_periods"])
    direction = _direction(df, ema_periods)

    mom_score = momentum_mod.momentum_score(df, direction=direction)
    regime = momentum_mod.detect_momentum_regime(df, lookback=config.regime["lookback"])
    if regime.state == "exhaustion":
        mom_score = max(0.0, mom_score - config.regime["exhaustion_penalty"])
    elif regime.state == "expansion":
        mom_score = min(100.0, mom_score + config.regime["expansion_bonus"])

    vol_state = volatility_mod.volatility_state(df, atr_period=config.indicators["atr_period"])

    components = {
        "momentum": mom_score,
        "trend": trend_mod.trend_score(df, periods=ema_periods),
        "volume": volume_mod.volume_score(df, direction=direction),
        "volatility": _VOLATILITY_REGIME_SCORE[vol_state.regime],
    }

    weighted = {k: components[k] * weights[k] for k in weights}
    total = sum(weighted.values())

    metadata = {
        "pair": pair,
        "latest_close": float(df["close"].iloc[-1]),
        "latest_timestamp": int(df["ts"].iloc[-1]) if "ts" in df.columns else None,
        "volatility_regime": vol_state.regime,
        "regime_strength": regime.strength,
    }

    return MomentumScoreBreakdown(
        total=total,
        components=components,
        weighted=weighted,
        direction=direction,
        regime=regime.state,
        metadata=metadata,
    )
