"""Backtest comparison: EW composite strategy vs buy & hold, EMA crossover,
and momentum baselines, using vectorbt.

Usage:
    python -m kraken_ew.backtest.run_backtest --pairs XBTUSD,ETHUSD
"""

from __future__ import annotations

import pandas as pd
import vectorbt as vbt

from kraken_ew.backtest import baselines
from kraken_ew.backtest.strategy_signals import build_signals, rolling_score_series
from kraken_ew.config import load_risk_config, load_scoring_config
from kraken_ew.data import ohlcv_store

INIT_CASH = 10_000.0
FEES = 0.0026  # Kraken taker fee, ~0.26%


def _portfolio_stats(name: str, pf: vbt.Portfolio) -> dict:
    trades = pf.trades
    return {
        "strategy": name,
        "total_return_pct": pf.total_return() * 100,
        "sharpe": pf.sharpe_ratio(),
        "sortino": pf.sortino_ratio(),
        "calmar": pf.calmar_ratio(),
        "max_drawdown_pct": pf.max_drawdown() * 100,
        "win_rate_pct": trades.win_rate() * 100 if trades.count() > 0 else float("nan"),
        "num_trades": trades.count(),
    }


def _infer_freq(ts: pd.Series) -> str:
    """Infer a pandas freq string from the median spacing of the ts (seconds)
    column. Robust to occasional missing bars (which would otherwise leave the
    DatetimeIndex freq as None and break vectorbt's annualization)."""
    median_sec = ts.diff().dropna().median()
    minutes = int(round(median_sec / 60))
    return f"{minutes}min" if minutes < 1440 else f"{minutes // 1440}d"


def run_comparison(pair: str, df: pd.DataFrame) -> pd.DataFrame:
    scoring_config = load_scoring_config()
    risk_config = load_risk_config()

    close = df["close"]
    close.index = pd.to_datetime(df["ts"], unit="s", utc=True)
    freq = _infer_freq(df["ts"])

    results = []

    # --- EW composite strategy ---
    scores = rolling_score_series(df, scoring_config)
    entries, exits, short_entries, short_exits = build_signals(
        df,
        scores,
        long_entry=risk_config.score_thresholds["long_entry"],
        short_entry=risk_config.score_thresholds["short_entry"],
        exit_threshold=risk_config.score_thresholds["exit"],
    )
    for s in (entries, exits, short_entries, short_exits):
        s.index = close.index

    pf_ew = vbt.Portfolio.from_signals(
        close,
        entries=entries,
        exits=exits,
        short_entries=short_entries,
        short_exits=short_exits,
        init_cash=INIT_CASH,
        fees=FEES,
        freq=freq,
    )
    results.append(_portfolio_stats("ew_composite", pf_ew))

    # --- Buy & hold ---
    bh_entries, bh_exits = baselines.buy_and_hold_signals(df)
    bh_entries.index = close.index
    bh_exits.index = close.index
    pf_bh = vbt.Portfolio.from_signals(close, entries=bh_entries, exits=bh_exits, init_cash=INIT_CASH, fees=FEES, freq=freq)
    results.append(_portfolio_stats("buy_and_hold", pf_bh))

    # --- EMA crossover ---
    ema_entries, ema_exits = baselines.ema_crossover_signals(df)
    ema_entries.index = close.index
    ema_exits.index = close.index
    pf_ema = vbt.Portfolio.from_signals(close, entries=ema_entries, exits=ema_exits, init_cash=INIT_CASH, fees=FEES, freq=freq)
    results.append(_portfolio_stats("ema_crossover", pf_ema))

    # --- Momentum (RSI) ---
    mom_entries, mom_exits = baselines.momentum_signals(df)
    mom_entries.index = close.index
    mom_exits.index = close.index
    pf_mom = vbt.Portfolio.from_signals(close, entries=mom_entries, exits=mom_exits, init_cash=INIT_CASH, fees=FEES, freq=freq)
    results.append(_portfolio_stats("momentum", pf_mom))

    out = pd.DataFrame(results).set_index("strategy")
    out["pair"] = pair
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", required=True, help="Comma-separated Kraken altnames, e.g. XBTUSD,ETHUSD")
    parser.add_argument("--interval", type=int, default=1440)
    args = parser.parse_args()

    con = ohlcv_store.connect()
    for pair in args.pairs.split(","):
        df = ohlcv_store.read_ohlcv(con, pair, args.interval)
        if df.empty:
            print(f"No data for {pair} @ {args.interval}m; run fetch_history first.")
            continue
        print(f"\n=== {pair} @ {args.interval}m ({len(df)} bars) ===")
        result = run_comparison(pair, df)
        print(result.round(2).to_string())
