# Roadmap

## MVP (Phase 1) — done in this pass

- [x] Project scaffolding, config system (`config/*.yaml`)
- [x] Kraken REST data layer + DuckDB store
- [x] Indicator engines: trend, momentum, volatility, volume, structure
- [x] Wave detection: ZigZag/fractal pivots, Fibonacci, impulse/ABC pattern
      matchers, wave validity scoring
- [x] Composite scoring model (weighted 0-100 + breakdown)
- [x] Decision logger (JSON + markdown)
- [x] Backtest framework (vectorbt) vs. buy & hold / EMA crossover / momentum
      baselines
- [x] Paper trading runner (CLI subprocess against Kraken's paper ledger)
- [x] CLI (`kraken-ew fetch|score|backtest|paper-run`)
- [x] Documentation: research, architecture, roadmap, falsification plan

**Estimated effort for this pass**: ~1 day of focused development (achieved
in a single session here, but a human team replicating this with proper
review/testing cycles should budget 1-2 weeks).

## Near-term follow-ups (still Phase 1 polish, no new phase)

- [ ] Run `kraken paper-run` on a schedule (cron/launchd) for a few weeks to
      accumulate real paper-trading history before drawing conclusions.
- [ ] Expand `tests/` coverage for `ohlcv_store` (currently only exercised
      via integration, not unit tests) and edge cases in `patterns.py`
      (e.g. fewer than 6/4 pivots available).
- [ ] Re-run the backtest periodically as more data accumulates (Kraken's
      720-candle cap means the dataset slowly extends over time).
- [ ] Tune `config/scoring_weights.yaml` and `config/risk.yaml` thresholds
      based on paper-trading results — current values are reasonable
      starting defaults, not yet empirically validated.

## Phase 2: ML evaluation (2-4 weeks)

1. Build a feature/label extraction pipeline from historical `ScoreBreakdown`
   components + raw indicators (1 week).
2. Train/validate XGBoost, Random Forest, LightGBM with walk-forward splits
   (1 week).
3. Compare ML-gated vs. composite-only vs. baselines via the existing
   vectorbt harness (a few days).
4. **Go/no-go decision**: adopt ML gating only if it materially improves
   out-of-sample Sharpe. Document the result either way in an updated
   `falsification_plan.md`.

## Phase 3: multi-exchange + dashboard (3-6 weeks)

1. CCXT integration for Binance/Coinbase/Bybit OHLCV, extend `ohlcv` schema
   with an `exchange` column (1-2 weeks).
2. Streamlit dashboard: current wave count, confidence score, open paper
   positions, recent decision log entries, backtest comparison charts
   (1-2 weeks).
3. (Optional, if multi-user/product need emerges) FastAPI wrapper + React
   frontend (additional 2-4 weeks).

## Phase 4: live execution + production infra (timeline TBD, gated on approval)

**Not started. Requires explicit separate user approval before any
implementation work begins**, given real-money risk.

1. Circuit breakers wired as hard pre-trade gates (`config/risk.yaml`
   drawdown limits).
2. Live order path via `kraken_order_buy`/`kraken_order_sell` (MCP, guarded
   mode, `acknowledged: true`), mirroring the paper runner's structure.
3. Human-in-the-loop confirmation for an initial trial period.
4. DuckDB → PostgreSQL/TimescaleDB migration if/when concurrency or data
   volume requires it.
5. Containerized deployment + scheduled jobs + secrets management.

## Production timeline (rough, all phases)

| Phase | Duration | Cumulative |
|---|---|---|
| 1 (MVP) | ~1 day (this session) / 1-2 weeks (team) | done |
| 1 polish + paper trading observation | 2-4 weeks (mostly waiting/observing) | ~1 month |
| 2 (ML evaluation) | 2-4 weeks | ~2 months |
| 3 (multi-exchange + dashboard) | 3-6 weeks | ~3-4 months |
| 4 (live execution + production) | TBD, gated on approval + Phase 1-3 results | ~4-6+ months |

This timeline assumes the falsification checks in
`docs/falsification_plan.md` don't kill the strategy earlier — if Phase 1's
backtest results (or the Phase 1 polish period's paper-trading results) show
the EW composite strategy doesn't beat the baselines on a risk-adjusted
basis, the honest move is to stop here (or pivot the strategy) rather than
proceed to Phase 2+.
