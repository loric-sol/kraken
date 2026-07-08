"""Paper trading runner: fetch recent data -> compute composite score ->
if a threshold is crossed and no open position, size per risk.yaml and place
a paper order via the Kraken CLI -> write a decision log entry.

Usage:
    python -m kraken_ew.live.paper_runner --pairs XBTUSD,ETHUSD --once
    python -m kraken_ew.live.paper_runner --pairs XBTUSD,ETHUSD --interval-seconds 3600
"""

from __future__ import annotations

import time

from kraken_ew.config import AppConfig, load_config
from kraken_ew.data import kraken_rest, ohlcv_store
from kraken_ew.decisionlog.logger import log_decision
from kraken_ew.indicators.volatility import atr
from kraken_ew.live import kraken_paper_cli
from kraken_ew.scoring.composite import compute_score

# Asset code extracted from a Kraken altname like "XBTUSD" -> "XBT", used to
# look up the paper balance for that asset.
_ASSET_FROM_PAIR = {
    "XBTUSD": "XBT",
    "ETHUSD": "ETH",
    "SOLUSD": "SOL",
    "AVAXUSD": "AVAX",
    "XDGUSD": "XDG",
}

# Minimum quote-currency (USD) value of a position to be considered "open".
MIN_POSITION_VALUE_USD = 10.0


def _has_open_position(pair: str, balances: dict, last_price: float) -> bool:
    asset = _ASSET_FROM_PAIR.get(pair)
    bal = balances.get("balances", {}).get(asset, {}) if asset else {}
    total = bal.get("total", 0.0)
    return (total * last_price) >= MIN_POSITION_VALUE_USD


def run_once(pairs: list[str], config: AppConfig, interval: int = 60, db_path=None) -> None:
    con = ohlcv_store.connect(db_path) if db_path else ohlcv_store.connect()
    risk = config.risk
    thresholds = risk.score_thresholds

    status = kraken_paper_cli.paper_status()
    balances = kraken_paper_cli.paper_balance()
    portfolio_value = status["current_value"]

    for pair in pairs:
        # Refresh recent candles for this pair so scoring is up to date.
        rows, _ = kraken_rest.get_ohlc(pair, interval=interval)
        ohlcv_store.upsert_ohlcv(con, pair, interval, rows)
        df = ohlcv_store.read_ohlcv(con, pair, interval)
        if df.empty:
            continue

        breakdown = compute_score(df, pair, config.scoring)
        last_price = float(df["close"].iloc[-1])
        has_position = _has_open_position(pair, balances, last_price)

        action = "no_action"
        order_result = None

        if not has_position and breakdown.total >= thresholds["long_entry"] and breakdown.direction == "long":
            atr_value = float(atr(df, period=config.scoring.indicators["atr_period"]).iloc[-1])
            stop_distance = atr_value * risk.stop_loss["atr_multiplier"]
            risk_amount = portfolio_value * risk.position_sizing["risk_per_trade_pct"] / 100
            volume = round(risk_amount / stop_distance, 6) if stop_distance > 0 else 0.0

            if volume > 0:
                order_result = kraken_paper_cli.paper_buy(pair, volume)
                action = "paper_buy"

        elif has_position and breakdown.total < thresholds["exit"]:
            asset = _ASSET_FROM_PAIR.get(pair)
            bal = balances.get("balances", {}).get(asset, {})
            volume = bal.get("total", 0.0)
            if volume > 0:
                order_result = kraken_paper_cli.paper_sell(pair, volume)
                action = "paper_sell"

        risk_params = {
            **thresholds,
            "risk_per_trade_pct": risk.position_sizing["risk_per_trade_pct"],
            "atr_multiplier": risk.stop_loss["atr_multiplier"],
            "order_result": order_result,
        }
        log_decision(pair, breakdown, action, risk_params)
        print(f"{pair}: score={breakdown.total:.1f} dir={breakdown.direction} action={action}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", required=True, help="Comma-separated Kraken altnames, e.g. XBTUSD,ETHUSD")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=3600, help="Loop sleep interval if not --once")
    args = parser.parse_args()

    config = load_config()
    pairs = args.pairs.split(",")

    if args.once:
        run_once(pairs, config, interval=args.interval)
    else:
        while True:
            run_once(pairs, config, interval=args.interval)
            time.sleep(args.interval_seconds)
