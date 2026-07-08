"""Walk-forward evaluation: run the EW composite vs. baselines across many
consecutive, non-overlapping time windows and report whether any edge is
*consistent* or concentrated in one lucky window.

The EW composite is a rule-based strategy (no fitted parameters), so this is
not a train/test split -- it's an out-of-sample *consistency* check. A single
backtest can look great by landing on a favourable regime; if the strategy
only beats the baselines in 1 of N windows, that "edge" is noise.

Each window contains `warmup` bars (so EMA200 etc. are valid before scoring
begins) plus a `test` segment that the metrics effectively reflect. Windows
step forward by `test` bars so the test segments do not overlap.

Usage:
    from kraken_ew.backtest.walk_forward import walk_forward
    summary, per_window = walk_forward(df, config, warmup=240, test=160)
"""

from __future__ import annotations

import pandas as pd

from kraken_ew.backtest.run_backtest import run_comparison
from kraken_ew.config import ScoringConfig  # noqa: F401  (documents the dep)

DEFAULT_WARMUP = 240   # EMA200 + buffer
DEFAULT_TEST = 160     # ~non-overlapping evaluation segment


def walk_forward(
    df: pd.DataFrame,
    warmup: int = DEFAULT_WARMUP,
    test: int = DEFAULT_TEST,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `run_comparison` over rolling [i : i+warmup+test] windows that step
    by `test` bars (so evaluation segments don't overlap).

    Returns (summary, per_window):
      - per_window: one row per window per strategy with returns/sharpe/trades
      - summary: per-strategy aggregates across windows, plus an
        `ew_beats_momentum_pct` / `ew_beats_bh_pct` consistency score.
    """
    window = warmup + test
    if len(df) < window:
        raise ValueError(f"need >= {window} bars for one window; have {len(df)}")

    records = []
    win_id = 0
    start = 0
    while start + window <= len(df):
        sub = df.iloc[start : start + window].reset_index(drop=True)
        res = run_comparison("wf", sub)
        d0 = pd.to_datetime(sub["ts"].iloc[0], unit="s", utc=True).date()
        d1 = pd.to_datetime(sub["ts"].iloc[-1], unit="s", utc=True).date()
        for strat, row in res.iterrows():
            records.append(
                {
                    "window": win_id,
                    "start": d0,
                    "end": d1,
                    "strategy": strat,
                    "return_pct": row["total_return_pct"],
                    "sharpe": row["sharpe"],
                    "num_trades": row["num_trades"],
                }
            )
        win_id += 1
        start += test

    per_window = pd.DataFrame(records)

    # Pivot EW vs momentum / buy_and_hold per window for the consistency score.
    piv = per_window.pivot_table(index="window", columns="strategy", values="return_pct")
    n = len(piv)
    summary = (
        per_window.groupby("strategy")
        .agg(
            mean_return_pct=("return_pct", "mean"),
            median_return_pct=("return_pct", "median"),
            std_return_pct=("return_pct", "std"),
            mean_trades=("num_trades", "mean"),
            windows=("return_pct", "count"),
        )
        .round(2)
    )
    if "ew_composite" in piv and "momentum" in piv:
        summary.loc["ew_composite", "beats_momentum_pct"] = round(
            (piv["ew_composite"] > piv["momentum"]).mean() * 100, 1
        )
    if "ew_composite" in piv and "buy_and_hold" in piv:
        summary.loc["ew_composite", "beats_bh_pct"] = round(
            (piv["ew_composite"] > piv["buy_and_hold"]).mean() * 100, 1
        )
    summary.attrs["n_windows"] = n
    return summary, per_window
