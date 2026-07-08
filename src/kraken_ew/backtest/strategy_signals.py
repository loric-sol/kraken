"""Turns the composite wave score into entry/exit signal series for backtesting.

NOTE on lookahead bias: `compute_score` uses ZigZag pivots, which include a
*provisional* final pivot for the swing currently in progress (it can move as
new bars arrive). Computing the score at each bar using only data up to and
including that bar (as done in `rolling_score_series`) avoids using future
data, but the provisional-pivot behavior means a score computed "as of" bar i
could differ slightly from what would have been seen live at bar i if Kraken
later revises that candle. This is a known, documented limitation of ZigZag-
based backtests and is mentioned in docs/falsification_plan.md.
"""

from __future__ import annotations

import pandas as pd

from kraken_ew.config import ScoringConfig
from kraken_ew.scoring.composite import compute_score

MIN_BARS = 60  # need enough history for EMA200 etc. before scoring is meaningful


def rolling_score_series(df: pd.DataFrame, config: ScoringConfig, min_bars: int = MIN_BARS) -> pd.DataFrame:
    """Compute the composite score at every bar from `min_bars` onward, using
    only data available up to and including that bar.

    Returns a DataFrame indexed like `df` (from min_bars onward) with columns
    total, direction.
    """
    records = []
    for i in range(min_bars, len(df)):
        window = df.iloc[: i + 1]
        breakdown = compute_score(window, pair="backtest", config=config)
        records.append({"index": i, "total": breakdown.total, "direction": breakdown.direction})

    result = pd.DataFrame(records).set_index("index")
    return result


def build_signals(
    df: pd.DataFrame,
    scores: pd.DataFrame,
    long_entry: float = 70,
    short_entry: float = 70,
    exit_threshold: float = 40,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Build (entries, exits, short_entries, short_exits) boolean Series
    aligned to `df.index`, derived from `scores` (output of
    `rolling_score_series`).

    - Long entry when score >= long_entry and direction == "long"
    - Short entry when score >= short_entry and direction == "short"
    - Exit (either side) when score < exit_threshold
    """
    n = len(df)
    entries = pd.Series(False, index=df.index)
    exits = pd.Series(False, index=df.index)
    short_entries = pd.Series(False, index=df.index)
    short_exits = pd.Series(False, index=df.index)

    for i, row in scores.iterrows():
        if i >= n:
            continue
        if row["total"] >= long_entry and row["direction"] == "long":
            entries.iloc[i] = True
        elif row["total"] >= short_entry and row["direction"] == "short":
            short_entries.iloc[i] = True

        if row["total"] < exit_threshold:
            exits.iloc[i] = True
            short_exits.iloc[i] = True

    return entries, exits, short_entries, short_exits
