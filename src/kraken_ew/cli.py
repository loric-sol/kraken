"""Top-level CLI for the Elliott Wave trading system.

Crypto commands (Kraken):   fetch, score, backtest, paper-run
Stock + options commands:   stock-fetch, stock-score, stock-scan, stock-run, stock-status
"""

from __future__ import annotations

import typer

from kraken_ew.config import load_config
from kraken_ew.data import fetch_history, ohlcv_store
from kraken_ew.decisionlog.logger import log_decision
from kraken_ew.scoring.composite import compute_score

app = typer.Typer(help="Elliott Wave + quant confirmation trading system")


# ──────────────────────────────────────────────
# Crypto / Kraken commands (original)
# ──────────────────────────────────────────────

@app.command()
def fetch(pair: str = typer.Option(..., help="Kraken altname, e.g. XBTUSD"), interval: int = 60):
    """Backfill OHLCV history for a Kraken pair."""
    n = fetch_history.backfill(pair, interval=interval)
    typer.echo(f"Inserted {n} new rows for {pair} @ {interval}m")


@app.command()
def score(pair: str = typer.Option(..., help="Kraken altname, e.g. XBTUSD"), interval: int = 1440):
    """Print composite wave score for the latest bar (Kraken pair)."""
    config = load_config()
    con = ohlcv_store.connect()
    df = ohlcv_store.read_ohlcv(con, pair, interval)
    if df.empty:
        typer.echo(f"No data for {pair}; run `kraken-ew fetch --pair {pair}` first.")
        raise typer.Exit(1)
    breakdown = compute_score(df, pair, config.scoring)
    typer.echo(f"{pair} @ {interval}m  total={breakdown.total:.1f}  direction={breakdown.direction}")
    for k, v in breakdown.components.items():
        typer.echo(f"  {k:16s} {v:6.1f}  -> weighted {breakdown.weighted[k]:5.2f}")
    typer.echo(f"  wave: {breakdown.metadata['wave_label']} ({breakdown.metadata['wave_position']})")
    if breakdown.metadata["wave_rule_violations"]:
        typer.echo(f"  violations: {breakdown.metadata['wave_rule_violations']}")
    path = log_decision(pair, breakdown, "score_check", config.risk.score_thresholds)
    typer.echo(f"  decision log: {path}")


@app.command()
def backtest(pairs: str = typer.Option(..., help="Comma-separated Kraken altnames"), interval: int = 1440):
    """Run EW composite vs baseline backtest (Kraken pairs)."""
    from kraken_ew.backtest.run_backtest import run_comparison
    con = ohlcv_store.connect()
    for pair in pairs.split(","):
        df = ohlcv_store.read_ohlcv(con, pair, interval)
        if df.empty:
            typer.echo(f"No data for {pair}; run fetch first.")
            continue
        typer.echo(f"\n=== {pair} @ {interval}m ({len(df)} bars) ===")
        typer.echo(run_comparison(pair, df).round(2).to_string())


@app.command(name="paper-run")
def paper_run(
    pairs: str = typer.Option(..., help="Comma-separated Kraken altnames"),
    interval: int = 60,
):
    """Crypto paper trading loop (fetch → score → paper trade → log)."""
    from kraken_ew.live.paper_runner import run_once
    config = load_config()
    run_once(pairs.split(","), config, interval=interval)


# ──────────────────────────────────────────────
# Stock + options commands
# ──────────────────────────────────────────────

@app.command(name="stock-fetch")
def stock_fetch(
    ticker: str = typer.Option(..., help="Stock ticker, e.g. SPY"),
    interval: int = typer.Option(1440, help="Bar interval in minutes (60=hourly, 1440=daily)"),
    source: str = typer.Option("auto", help="Data source: auto | massive | yfinance"),
):
    """Fetch OHLCV history for a stock ticker (Massive preferred, yfinance fallback)."""
    from kraken_ew.data import equity_source
    rows, used = equity_source.fetch_equity_ohlcv(ticker, interval=interval, source=source)
    if not rows:
        typer.echo(f"No data returned for {ticker} (source={used}).")
        raise typer.Exit(1)
    con = ohlcv_store.connect()
    inserted = ohlcv_store.upsert_ohlcv(con, ticker, interval, rows)
    typer.echo(f"[{used}] Fetched {len(rows)} bars, inserted {inserted} new rows for {ticker} @ {interval}m")


@app.command(name="stock-score")
def stock_score(
    ticker: str = typer.Option(..., help="Stock ticker, e.g. SPY"),
    interval: int = 1440,
):
    """Print EW composite score + options setup for a stock ticker."""
    from kraken_ew.data import yfinance_client
    from kraken_ew.indicators.volatility import atr
    from kraken_ew.options.chain import select_contract
    from kraken_ew.options.sizing import size_position
    import yaml
    from kraken_ew.config import PROJECT_ROOT

    config = load_config()
    con = ohlcv_store.connect()
    df = ohlcv_store.read_ohlcv(con, ticker, interval)
    if df.empty or len(df) < 60:
        typer.echo(f"Not enough data for {ticker}; run `kraken-ew stock-fetch --ticker {ticker}` first.")
        raise typer.Exit(1)

    breakdown = compute_score(df, ticker, config.scoring)
    spot = float(df["close"].iloc[-1])
    atr_val = float(atr(df, period=config.scoring.indicators["atr_period"]).iloc[-1])

    typer.echo(f"\n{ticker} @ {interval}m  spot=${spot:.2f}  total={breakdown.total:.1f}  direction={breakdown.direction}")
    for k, v in breakdown.components.items():
        typer.echo(f"  {k:16s} {v:6.1f}  -> weighted {breakdown.weighted[k]:5.2f}")
    typer.echo(f"  wave: {breakdown.metadata['wave_label']} ({breakdown.metadata['wave_position']})")
    if breakdown.metadata["wave_rule_violations"]:
        typer.echo(f"  violations: {breakdown.metadata['wave_rule_violations']}")
    typer.echo(f"  ATR(14): {atr_val:.4f}")

    if breakdown.total >= 70 and breakdown.direction != "neutral":
        opt_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "options.yaml"))
        chain = yfinance_client.get_options_chain(
            ticker,
            dte_min=opt_cfg["selection"]["dte_min"],
            dte_max=opt_cfg["selection"]["dte_max"],
        )
        contract = select_contract(
            ticker=ticker, chain=chain, direction=breakdown.direction,
            spot=spot,
            delta_target=opt_cfg["selection"]["delta_target"],
            delta_tolerance=opt_cfg["selection"]["delta_tolerance"],
            risk_free=opt_cfg["greeks"]["risk_free_rate"],
        )
        if contract:
            sizing = size_position(
                contract=contract,
                portfolio_value=10_000.0,
                premium_risk_pct=opt_cfg["sizing"]["premium_risk_pct"],
                max_contracts=opt_cfg["sizing"]["max_contracts"],
                max_position_pct=opt_cfg["sizing"]["max_position_pct"],
            )
            typer.echo(f"\n  ✅ SIGNAL — {breakdown.direction.upper()}")
            typer.echo(f"  Option:    {contract.option_type.upper()} ${contract.strike} exp {contract.expiry} ({contract.dte} DTE)")
            typer.echo(f"  Mid:       ${contract.mid:.2f}  bid=${contract.bid:.2f}  ask=${contract.ask:.2f}")
            typer.echo(f"  IV:        {contract.iv*100:.1f}%")
            typer.echo(f"  Greeks:    delta={contract.greeks.delta:.3f}  gamma={contract.greeks.gamma:.4f}  theta={contract.greeks.theta:.4f}/day  vega={contract.greeks.vega:.4f}")
            typer.echo(f"  Size:      {sizing['contracts']} contracts  @ ${sizing['cost_per_contract']:.2f}/contract")
            typer.echo(f"  Premium:   ${sizing['premium_total']:.2f}  ({sizing['risk_pct']:.1f}% of portfolio)")
            typer.echo(f"  T1 (+1%):  +${sizing['t1_pnl']:.2f}")
            typer.echo(f"  T2 (+2%):  +${sizing['t2_pnl']:.2f}")
            typer.echo(f"  T3 (+3%):  +${sizing['t3_pnl']:.2f}")
            typer.echo(f"  Max loss:  -${sizing['max_loss']:.2f}")
        else:
            typer.echo("  Signal triggered but no suitable option contract found (check chain DTE/liquidity).")
    else:
        typer.echo(f"  No signal (score {breakdown.total:.1f} < 70 or direction=neutral)")

    path = log_decision(ticker, breakdown, "stock_score_check", config.risk.score_thresholds)
    typer.echo(f"  decision log: {path}")


@app.command(name="stock-scan")
def stock_scan(
    tickers: str = typer.Option("SPY,QQQ,AAPL,TSLA,NVDA", help="Comma-separated tickers"),
    interval: int = 1440,
):
    """Scan all tickers and show scores + best options setup for signals."""
    from kraken_ew.data import equity_source
    from kraken_ew.indicators.volatility import atr as calc_atr
    from kraken_ew.options.chain import select_contract
    from kraken_ew.options.sizing import size_position
    import yaml
    from kraken_ew.config import PROJECT_ROOT

    config = load_config()
    opt_cfg = yaml.safe_load(open(PROJECT_ROOT / "config" / "options.yaml"))
    con = ohlcv_store.connect()

    import time as _time
    fresh_cutoff = _time.time() - 4 * 86400  # daily bars: reuse if <4 days old
    for ticker in tickers.split(","):
        df = ohlcv_store.read_ohlcv(con, ticker, interval)
        is_fresh = (not df.empty) and len(df) >= 60 and float(df["ts"].iloc[-1]) >= fresh_cutoff
        if not is_fresh:  # only hit Massive (5 req/min) when data is stale/missing
            try:
                rows, _ = equity_source.fetch_equity_ohlcv(ticker, interval=interval)
            except Exception as exc:  # loud per-ticker skip, never silent bad-data
                typer.echo(f"   {ticker:5s}  DATA ERROR: {exc}")
                continue
            ohlcv_store.upsert_ohlcv(con, ticker, interval, rows)
            df = ohlcv_store.read_ohlcv(con, ticker, interval)
        if df.empty or len(df) < 60:
            typer.echo(f"{ticker}: skipped (insufficient data)")
            continue

        breakdown = compute_score(df, ticker, config.scoring)
        spot = float(df["close"].iloc[-1])
        atr_val = float(calc_atr(df, period=config.scoring.indicators["atr_period"]).iloc[-1])
        flag = "✅" if breakdown.total >= 70 else ("👀" if breakdown.total >= 60 else "  ")

        typer.echo(f"\n{flag} {ticker:5s}  spot=${spot:>9.2f}  score={breakdown.total:5.1f}  dir={breakdown.direction:7s}  wave={breakdown.metadata['wave_label']}")

        if breakdown.total >= 70 and breakdown.direction != "neutral":
            # Options-chain suggestion is best-effort and must never crash the
            # scan. Chains come from yfinance (ancillary display only, not the
            # scored OHLCV which is Massive-only).
            try:
                from kraken_ew.data import yfinance_client
                chain = yfinance_client.get_options_chain(ticker, dte_min=opt_cfg["selection"]["dte_min"], dte_max=opt_cfg["selection"]["dte_max"])
                contract = select_contract(ticker=ticker, chain=chain, direction=breakdown.direction, spot=spot,
                    delta_target=opt_cfg["selection"]["delta_target"], delta_tolerance=opt_cfg["selection"]["delta_tolerance"],
                    risk_free=opt_cfg["greeks"]["risk_free_rate"])
                if contract:
                    sizing = size_position(contract=contract, portfolio_value=10_000.0,
                        premium_risk_pct=opt_cfg["sizing"]["premium_risk_pct"],
                        max_contracts=opt_cfg["sizing"]["max_contracts"],
                        max_position_pct=opt_cfg["sizing"]["max_position_pct"])
                    typer.echo(f"       {contract.option_type.upper()} ${contract.strike} exp {contract.expiry} ({contract.dte}DTE)  "
                               f"mid=${contract.mid:.2f}  delta={contract.greeks.delta:.2f}  IV={contract.iv*100:.0f}%  "
                               f"{sizing['contracts']}ct @ ${sizing['premium_total']:.0f} total  "
                               f"T1=+${sizing['t1_pnl']:.0f} T2=+${sizing['t2_pnl']:.0f} T3=+${sizing['t3_pnl']:.0f}")
            except Exception as exc:
                typer.echo(f"       (options lookup unavailable: {exc})")


@app.command(name="stock-run")
def stock_run(
    tickers: str = typer.Option("SPY,QQQ,AAPL,TSLA,NVDA", help="Comma-separated tickers"),
    interval: int = 1440,
):
    """Run the options paper trading loop for stocks (fetch → score → trade → log)."""
    from kraken_ew.live.stock_runner import run_once
    config = load_config()
    run_once(tickers.split(","), config, interval=interval)


@app.command(name="stock-status")
def stock_status():
    """Show open options positions and P&L summary."""
    from kraken_ew.live import stock_paper

    con = stock_paper.connect()
    summary = stock_paper.portfolio_summary(con)
    typer.echo(f"\n{'─'*50}")
    typer.echo(f"  Starting cash:       ${summary['starting']:>10,.2f}")
    typer.echo(f"  Realized P&L:        ${summary['realized_pnl']:>+10,.2f}")
    typer.echo(f"  Premium at risk:     ${summary.get('open_premium_at_risk', summary.get('open_premium', 0.0)):>10,.2f}")
    typer.echo(f"  Cash remaining:      ${summary['cash_remaining']:>10,.2f}")
    typer.echo(f"  Total return:        {summary['total_return_pct']:>+9.2f}%")
    typer.echo(f"  Trades:              {summary['num_trades']}  ({summary['open_positions']} open)")
    typer.echo(f"{'─'*50}")

    open_pos = stock_paper.open_positions(con)
    if not open_pos.empty:
        typer.echo("\nOpen positions:")
        for _, p in open_pos.iterrows():
            typer.echo(f"  #{int(p['id'])} {p['ticker']} {p['option_type'].upper()} ${p['strike']} "
                       f"exp={p['expiry']}  {int(p['contracts'])}ct  entry=${p['entry_mid']:.2f}  "
                       f"cost=${p['entry_total']:.2f}  score={p['score']:.1f}")


if __name__ == "__main__":
    app()
