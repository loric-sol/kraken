"""Rolling score series for the momentum-engine strategy -- the momentum
counterpart to strategy_signals.rolling_score_series. Signal generation from
the resulting scores reuses strategy_signals.build_signals directly, since
that function only depends on a `total`/`direction` scores frame and has no
wave-specific logic.
"""

from __future__ import annotations

import pandas as pd

from kraken_ew.config import MomentumStrategyConfig
from kraken_ew.scoring.momentum_strategy import compute_momentum_score

MIN_BARS = 60  # need enough history for EMA200 etc. before scoring is meaningful


def rolling_momentum_score_series(df: pd.DataFrame, config: MomentumStrategyConfig, min_bars: int = MIN_BARS) -> pd.DataFrame:
    """Compute the momentum-engine score at every bar from `min_bars`
    onward, using only data available up to and including that bar."""
    records = []
    for i in range(min_bars, len(df)):
        window = df.iloc[: i + 1]
        breakdown = compute_momentum_score(window, pair="backtest", config=config)
        records.append({"index": i, "total": breakdown.total, "direction": breakdown.direction})

    return pd.DataFrame(records).set_index("index")
