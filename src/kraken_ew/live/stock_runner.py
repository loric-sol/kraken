"""Stock + options paper trading runner.

Flow: fetch OHLCV → compute EW composite score → if signal, fetch options
chain → select best contract → size position → log to stock_paper.duckdb +
decision log.
"""

from __future__ import annotations

import yaml
from pathlib import Path

from kraken_ew.config import AppConfig, load_config, PROJECT_ROOT
from kraken_ew.data import equity_source, ohlcv_store, yfinance_client
from kraken_ew.decisionlog.logger import log_decision
from kraken_ew.indicators.volatility import atr
from kraken_ew.live import stock_paper
from kraken_ew.options.chain import select_contract
from kraken_ew.options.sizing import size_position
from kraken_ew.scoring.composite import compute_score

_OPT_CFG_PATH = PROJECT_ROOT / "config" / "options.yaml"


def _load_options_config() -> dict:
    with open(_OPT_CFG_PATH) as f:
        return yaml.safe_load(f)


def run_once(
    tickers: list[str],
    config: AppConfig,
    interval: int = 1440,
    db_path=None,
) -> None:
    opt_cfg = _load_options_config()
    ohlcv_con = ohlcv_store.connect(db_path) if db_path else ohlcv_store.connect()
    paper_con = stock_paper.connect()
    risk = config.risk

    summary = stock_paper.portfolio_summary(paper_con)
    portfolio_value = summary["cash_remaining"]

    open_pos = stock_paper.open_positions(paper_con)

    for ticker in tickers:
        # refresh data (Massive preferred, yfinance fallback)
        rows, _ = equity_source.fetch_equity_ohlcv(ticker, interval=interval)
        ohlcv_store.upsert_ohlcv(ohlcv_con, ticker, interval, rows)
        df = ohlcv_store.read_ohlcv(ohlcv_con, ticker, interval)
        if df.empty or len(df) < 60:
            print(f"{ticker}: not enough data ({len(df)} bars)")
            continue

        breakdown = compute_score(df, ticker, config.scoring)
        score = breakdown.total
        direction = breakdown.direction
        spot = float(df["close"].iloc[-1])
        atr_val = float(atr(df, period=config.scoring.indicators["atr_period"]).iloc[-1])

        action = "no_action"
        contract = None
        sizing = None

        has_open = ticker in open_pos["ticker"].values if not open_pos.empty else False

        # --- check exit for open positions ---
        if has_open:
            pos_rows = open_pos[open_pos["ticker"] == ticker]
            for _, pos in pos_rows.iterrows():
                # fetch current mid from chain
                chain = yfinance_client.get_options_chain(
                    ticker,
                    dte_min=0,
                    dte_max=opt_cfg["selection"]["dte_max"] + 10,
                )
                current_mid = None
                if not chain.empty:
                    match = chain[
                        (chain["option_type"] == pos["option_type"]) &
                        (chain["strike"] == pos["strike"]) &
                        (chain["expiry"] == pos["expiry"])
                    ]
                    if not match.empty:
                        current_mid = float(match.iloc[0]["mid"])

                if current_mid is not None:
                    pnl_pct = (current_mid - pos["entry_mid"]) / pos["entry_mid"] * 100
                    dte_remaining = _dte(pos["expiry"])
                    should_exit = (
                        pnl_pct >= opt_cfg["exit_rules"]["profit_target_pct"] or
                        pnl_pct <= -opt_cfg["exit_rules"]["stop_loss_pct"] or
                        dte_remaining <= opt_cfg["exit_rules"]["dte_exit"] or
                        score < risk.score_thresholds["exit"]
                    )
                    if should_exit:
                        result = stock_paper.close_position(paper_con, int(pos["id"]), current_mid)
                        action = "close_position"
                        print(f"{ticker}: CLOSE {pos['option_type'].upper()} ${pos['strike']} "
                              f"exp={pos['expiry']}  P&L=${result['pnl']:+.2f} ({result['pnl_pct']:+.1f}%)")

        # --- check entry ---
        if not has_open and direction != "neutral" and score >= risk.score_thresholds.get(
            "long_entry" if direction == "long" else "short_entry", 70
        ):
            chain = yfinance_client.get_options_chain(
                ticker,
                dte_min=opt_cfg["selection"]["dte_min"],
                dte_max=opt_cfg["selection"]["dte_max"],
            )
            contract = select_contract(
                ticker=ticker,
                chain=chain,
                direction=direction,
                spot=spot,
                delta_target=opt_cfg["selection"]["delta_target"],
                delta_tolerance=opt_cfg["selection"]["delta_tolerance"],
                risk_free=opt_cfg["greeks"]["risk_free_rate"],
            )

            if contract and contract.mid > 0:
                sizing = size_position(
                    contract=contract,
                    portfolio_value=portfolio_value,
                    premium_risk_pct=opt_cfg["sizing"]["premium_risk_pct"],
                    max_contracts=opt_cfg["sizing"]["max_contracts"],
                    max_position_pct=opt_cfg["sizing"]["max_position_pct"],
                )
                if sizing["contracts"] > 0:
                    stock_paper.open_position(
                        paper_con,
                        ticker=ticker,
                        option_type=contract.option_type,
                        expiry=contract.expiry,
                        dte=contract.dte,
                        strike=contract.strike,
                        contracts=sizing["contracts"],
                        entry_mid=contract.mid,
                        score=score,
                        direction=direction,
                        metadata={
                            "delta": round(contract.greeks.delta, 3),
                            "iv": round(contract.iv, 4),
                            "atr": round(atr_val, 4),
                            "score_breakdown": breakdown.weighted,
                        },
                    )
                    action = "open_position"
                    print(f"{ticker}: BUY {contract.contracts if hasattr(contract,'contracts') else sizing['contracts']}x "
                          f"{contract.option_type.upper()} ${contract.strike} exp={contract.expiry} "
                          f"@ ${contract.mid:.2f}  delta={contract.greeks.delta:.2f}  "
                          f"cost=${sizing['premium_total']:.2f}")

        log_decision(ticker, breakdown, action, {
            **risk.score_thresholds,
            "contract": {
                "strike": contract.strike if contract else None,
                "expiry": contract.expiry if contract else None,
                "option_type": contract.option_type if contract else None,
                "mid": contract.mid if contract else None,
            } if contract else None,
            "sizing": sizing,
        })
        print(f"{ticker}: score={score:.1f} dir={direction} spot=${spot:.2f} action={action}")


def _dte(expiry_str: str) -> int:
    from datetime import date
    exp = date.fromisoformat(expiry_str)
    return (exp - date.today()).days
