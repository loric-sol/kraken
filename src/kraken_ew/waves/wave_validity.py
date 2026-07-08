"""Combines pivot detection + pattern matching into the "wave structure
validity" composite score component (weight: 30% by default)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from kraken_ew.waves.patterns import WaveCount, best_wave_count
from kraken_ew.waves.pivots import Pivot, zigzag_pivots


@dataclass
class WaveStructureResult:
    score: float  # 0-100, the "wave validity" composite component
    wave_count: WaveCount
    current_position: str
    pivots: list[Pivot]


_POSITION_LABELS: dict[str, str] = {
    "impulse_5": "likely_completing_wave_5_of_5",
    "corrective_abc": "likely_completing_wave_c_of_abc",
    "none": "no_clear_wave_count",
}


def wave_structure_score(df: pd.DataFrame, zigzag_threshold_pct: float = 5.0) -> WaveStructureResult:
    """Detect pivots via ZigZag and score the best-fitting wave count.

    Returns a 0-100 score plus the WaveCount, a human-readable label for the
    current position in the count, and the pivots used.
    """
    if "ts" not in df.columns and "timestamp" in df.columns:
        df = df.assign(ts=(df["timestamp"].astype("int64") // 10**9))

    pivots = zigzag_pivots(df, threshold_pct=zigzag_threshold_pct)
    wave_count = best_wave_count(pivots)

    position = _POSITION_LABELS.get(wave_count.label, "no_clear_wave_count")

    return WaveStructureResult(
        score=wave_count.confidence,
        wave_count=wave_count,
        current_position=position,
        pivots=pivots,
    )


def implied_direction(result: WaveStructureResult) -> Literal["long", "short", "neutral"]:
    """The directional bias implied by the detected wave count.

    - After an impulse up (direction="long" in match_impulse means wave1 was
      up), the next expected move is a correction down, then continuation up
      -- but for entry purposes near wave 4/5 completion, bias follows the
      impulse direction for wave 5 setups and reverses for ABC completions.
    - After an ABC correction, the expected move is a resumption of the
      pre-correction trend, which is `wave_count.direction` as defined in
      match_corrective_abc (it already encodes the *expected reversal*
      direction).
    """
    wc = result.wave_count
    if wc.label == "impulse_5":
        return wc.direction
    if wc.label == "corrective_abc":
        return wc.direction
    return "neutral"
