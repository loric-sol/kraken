"""Composite wave scoring model: combines the wave validity, Fibonacci
confluence, momentum, trend, volume, and market structure engines into a
single 0-100 score plus a per-component breakdown for explainability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from kraken_ew.config import ScoringConfig
from kraken_ew.indicators import momentum as momentum_mod
from kraken_ew.indicators import structure as structure_mod
from kraken_ew.indicators import trend as trend_mod
from kraken_ew.indicators import volume as volume_mod
from kraken_ew.waves.fibonacci import confluence_score, extension_levels, retracement_levels
from kraken_ew.waves.wave_validity import implied_direction, wave_structure_score

Direction = Literal["long", "short", "neutral"]


@dataclass
class ScoreBreakdown:
    total: float
    components: dict[str, float]
    weighted: dict[str, float]
    direction: Direction
    metadata: dict = field(default_factory=dict)


def _fib_confluence(df: pd.DataFrame, pivots, tolerance_pct: float) -> float:
    """Build fib level sets from the most recent pivots and score how many
    cluster near the current price.

    - Set 1: retracement levels of the most recent swing (pivots[-2] -> pivots[-1])
    - Set 2: extension levels projected from pivots[-2], sized by the
      pivots[-4] -> pivots[-3] swing (a prior impulse leg)
    """
    if len(pivots) < 2:
        return 0.0

    current_price = df["close"].iloc[-1]
    levels_sets = [retracement_levels(pivots[-2], pivots[-1])]

    if len(pivots) >= 4:
        levels_sets.append(extension_levels(pivots[-4], pivots[-3], pivots[-2]))

    return confluence_score(levels_sets, current_price, tolerance_pct=tolerance_pct)


def compute_score(df: pd.DataFrame, pair: str, config: ScoringConfig) -> ScoreBreakdown:
    """Run all engines on `df` and combine them per `config.weights` into a
    0-100 composite score with a full breakdown for the decision log."""
    weights = config.weights
    zigzag_threshold = config.pivots["zigzag_threshold_pct"]
    ema_periods = tuple(config.indicators["ema_periods"])
    fib_tolerance = config.fibonacci["confluence_tolerance_pct"]

    wave_result = wave_structure_score(df, zigzag_threshold_pct=zigzag_threshold)
    direction = implied_direction(wave_result)

    if direction == "neutral":
        trend_state = trend_mod.trend_state(df, periods=ema_periods)
        if trend_state.direction == "up":
            direction = "long"
        elif trend_state.direction == "down":
            direction = "short"
        # else stays "neutral"

    components: dict[str, float] = {
        "wave_validity": wave_result.score,
        "fib_confluence": _fib_confluence(df, wave_result.pivots, fib_tolerance),
    }

    if direction == "neutral":
        # No directional bias -- momentum/volume/structure scores are
        # direction-relative and meaningless without one. Score them at 0
        # so the composite total reflects "no actionable setup".
        components["momentum"] = 0.0
        components["trend"] = 0.0
        components["volume"] = 0.0
        components["structure"] = 0.0
    else:
        components["momentum"] = momentum_mod.momentum_score(df, direction=direction)
        components["trend"] = trend_mod.trend_score(df, periods=ema_periods)
        components["volume"] = volume_mod.volume_score(df, direction=direction)
        components["structure"] = structure_mod.structure_score(wave_result.pivots, direction=direction)

    weighted = {k: components[k] * weights[k] for k in weights}
    total = sum(weighted.values())

    metadata = {
        "pair": pair,
        "wave_label": wave_result.wave_count.label,
        "wave_position": wave_result.current_position,
        "wave_rule_violations": wave_result.wave_count.rule_violations,
        "num_pivots": len(wave_result.pivots),
        "latest_close": float(df["close"].iloc[-1]),
        "latest_timestamp": int(df["ts"].iloc[-1]) if "ts" in df.columns else None,
    }

    return ScoreBreakdown(total=total, components=components, weighted=weighted, direction=direction, metadata=metadata)
