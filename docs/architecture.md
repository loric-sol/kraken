# Architecture

This document describes the full target architecture for the Elliott Wave +
quantitative confirmation trading system, and explicitly marks what is built
in **Phase 1 (this MVP)** vs. future phases. See `docs/roadmap.md` for
timeline/sequencing and `docs/falsification_plan.md` for how Phase 1's
strategy is being validated.

## Phase overview

| Phase | Scope | Status |
|---|---|---|
| 1 | Kraken-only data, DuckDB, wave/indicator engines, composite scoring, decision log, vectorbt backtest vs. baselines, CLI-driven paper trading | **Built (this pass)** |
| 2 | ML evaluation layer (does a learned model improve on the rule-based composite score?) | Designed, not built |
| 3 | Multi-exchange data (CCXT: Binance/Coinbase/Bybit), dashboard, deeper fib/fractal confluence | Designed, not built |
| 4 | Live (real-money) execution, PostgreSQL/TimescaleDB migration, production infra | Designed, explicitly deferred pending separate approval |

---

## Phase 1 architecture (built)

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Kraken public   │────▶│  data/kraken_rest │────▶│  data/ohlcv_store   │
│  REST API        │     │  (OHLC/Ticker)    │     │  (DuckDB)           │
└─────────────────┘     └──────────────────┘     └─────────┬──────────┘
                                                              │
                  ┌───────────────────────────────────────────┴──────────────────────────┐
                  │                                                                        │
                  ▼                                                                        ▼
     ┌────────────────────────┐                                            ┌──────────────────────────┐
     │ indicators/             │                                            │ waves/                   │
     │  trend, momentum,       │                                            │  pivots (ZigZag/fractal) │
     │  volatility, volume,    │                                            │  fibonacci               │
     │  structure              │◀───────────uses pivots────────────────────│  patterns (impulse/ABC)  │
     └───────────┬─────────────┘                                            │  wave_validity           │
                  │                                                          └──────────────┬───────────┘
                  └─────────────────────────┬───────────────────────────────────────────────┘
                                              ▼
                                  ┌────────────────────────┐
                                  │ scoring/composite       │
                                  │  weighted 0-100 score   │
                                  │  + ScoreBreakdown        │
                                  └───────────┬─────────────┘
                                              │
                  ┌───────────────────────────┴───────────────────────────┐
                  ▼                                                        ▼
     ┌────────────────────────┐                              ┌──────────────────────────┐
     │ decisionlog/logger      │                              │ backtest/                 │
     │  JSON + markdown         │                              │  strategy_signals,        │
     │  "why this trade" record │                              │  baselines, run_backtest  │
     └────────────────────────┘                              │  (vectorbt)               │
                  ▲                                            └──────────────────────────┘
                  │
     ┌────────────┴─────────────┐
     │ live/                     │
     │  kraken_paper_cli         │──── subprocess ────▶ `kraken paper buy/sell/status` (Kraken CLI)
     │  paper_runner             │
     └───────────────────────────┘
                  ▲
                  │
     ┌────────────┴─────────────┐
     │ cli.py (kraken-ew)         │
     │  fetch | score | backtest | paper-run
     └───────────────────────────┘
```

### Data layer (Phase 1)
- **Source**: Kraken's public REST `/OHLC` endpoint (no API key needed).
  Hard limitation: returns only the most recent ~720 candles per interval
  regardless of `since` — so daily candles give ~2 years of history (used
  for backtesting) and hourly candles give ~30 days (used for live scoring).
  See `data/fetch_history.py` for details.
- **Storage**: DuckDB (`data/kraken_ew.duckdb`), a single `ohlcv` table keyed
  on `(pair, interval, ts)` with idempotent upserts.
- **Why DuckDB for Phase 1**: zero-ops, file-based, trivial to inspect with
  `duckdb` CLI or pandas, and the data volumes here (a few thousand rows per
  pair/interval) are tiny. No reason to run a database server for an MVP.

### Signal layer (Phase 1)
Each indicator module (`indicators/trend.py`, `momentum.py`, `volatility.py`,
`volume.py`, `structure.py`) is a small set of pure functions over a
`pd.DataFrame` — no shared base class or framework, per the "don't
over-engineer" project guideline. The wave modules
(`waves/pivots.py`, `fibonacci.py`, `patterns.py`, `wave_validity.py`) follow
the same style. See `docs/research_elliott_wave.md` for the EWT-to-code
mapping.

### Scoring layer (Phase 1)
`scoring/composite.py` combines all of the above into a single 0-100 score
using configurable weights (`config/scoring_weights.yaml`):

| Component | Weight |
|---|---|
| wave_validity | 30% |
| fib_confluence | 20% |
| momentum | 15% |
| trend | 15% |
| volume | 10% |
| structure | 10% |

The result is a `ScoreBreakdown` dataclass carrying both the total and every
component's raw + weighted value, plus metadata (wave label, rule
violations, pivot count) — this is what makes every decision explainable.

### Momentum-engine strategy (built, parallel to EW)
`scoring/momentum_strategy.py` is a second, independent scored strategy for
the falsification comparison: no wave counting or Fibonacci confluence, just
`config/momentum_weights.yaml`-weighted momentum (RSI/MACD/StochRSI
alignment + divergence + an expansion/exhaustion regime classifier added to
`indicators/momentum.py`), trend, volume, and volatility-regime components.
Direction comes from the EMA trend stack (falling back to MACD sign when the
stack is sideways) rather than a wave count. It exists so
`backtest/run_backtest.py` compares EW against a *quantified* momentum
strategy (`momentum_engine`), not just the single-indicator RSI-cross
baseline (`momentum` in `backtest/baselines.py`) — per the project's
constraint to compare against real alternatives, not a strawman. Signal
generation reuses `backtest/strategy_signals.build_signals` directly (it's
already strategy-agnostic); only score computation
(`backtest/momentum_strategy_signals.rolling_momentum_score_series`) is
momentum-specific. Not yet wired into `live/paper_runner.py` — that runner
is still EW-only.

### Decision log (Phase 1)
`decisionlog/logger.py` writes a JSON + markdown record for every score
check, paper trade, or (future) live trade, satisfying the "AI agent
explainability" requirement (wave count, indicator values, score breakdown,
risk parameters) cheaply — no separate explanation-generation system needed.

### Backtesting (Phase 1)
`backtest/run_backtest.py` uses **vectorbt** to compare the EW composite
strategy against three baselines (buy & hold, EMA crossover, RSI momentum)
on the same data, producing standard portfolio stats (total return, Sharpe,
Sortino, Calmar, max drawdown, win rate, trade count). See
`docs/falsification_plan.md` for results and interpretation.

### Paper trading (Phase 1)
`live/paper_runner.py` is a thin loop: fetch recent candles → compute score →
if a threshold is crossed and no position is open, size the position per
`config/risk.yaml` (ATR-based stop distance × risk % of portfolio) and place
a paper order via `live/kraken_paper_cli.py`, which shells out to the
already-installed `kraken` CLI's `paper buy/sell/status/balance` commands
(`-o json`). This reuses Kraken's own paper ledger as the single source of
truth for paper P&L — inspectable directly via `kraken paper status`.

---

## Phase 2 (designed, not built): ML evaluation layer

**Question to answer**: does a learned model (XGBoost / Random Forest /
LightGBM / a small NN) trained on the same features the composite score uses
(wave scores, momentum/volatility/volume/structure metrics, funding rates if
added) produce a materially better Sharpe ratio than the hand-weighted
composite score?

**Design**:
- Label: did price reach a defined profit target before the stop, within N
  bars, from each historical bar? (binary classification)
- Features: the same `ScoreBreakdown.components` values, plus raw indicator
  values (RSI, ATR%, EMA spread, OBV slope, etc.) and (if added) funding
  rate / open interest.
- Train/validate with walk-forward splits (never shuffle time-series data).
- Compare: ML-gated strategy (only take composite-score signals where
  `model.predict_proba() > threshold`) vs. the Phase 1 composite-only
  strategy, vs. baselines, on the same vectorbt harness.
- **Decision rule** (per project constraints): if ML does not improve
  Sharpe materially over the composite-only strategy on out-of-sample data,
  **reject ML** — don't ship a more complex system for no benefit.

This is *evaluation-only* in Phase 2; it does not change the live/paper
trading path unless it wins the comparison.

---

## Phase 3 (designed, not built): multi-exchange data + dashboard

### Multi-exchange data via CCXT
Add `data/ccxt_client.py` (or similar) using the `ccxt` library to pull
OHLCV from Binance, Coinbase, and Bybit alongside Kraken. Store with the same
`ohlcv` schema, adding an `exchange` column to the primary key
(`exchange, pair, interval, ts`). This enables:
- Cross-exchange price confluence checks
- Larger history windows (other exchanges may not have Kraken's 720-candle
  cap on their OHLCV endpoints)
- Funding rate / open interest / liquidation data for the Liquidity Engine
  described in the original spec (these are mostly futures-exchange
  concepts; Kraken Futures has some of this too via the already-installed
  CLI's `kraken futures *` commands).

### Dashboard: Streamlit vs. FastAPI + React

| | Streamlit | FastAPI + React |
|---|---|---|
| Time to first dashboard | Hours | Days-weeks |
| Customization ceiling | Moderate | High |
| Good fit for | Solo/small-team research dashboards, rapid iteration | Multi-user product, custom UX, mobile |
| Backend reuse | Direct Python calls into `kraken_ew` package | Needs a FastAPI layer wrapping `kraken_ew` |

**Recommendation for Phase 3**: start with **Streamlit** — it can directly
import `kraken_ew.scoring`, `kraken_ew.data.ohlcv_store`, etc. and render the
current wave count, confidence score, open positions (via
`kraken_paper_cli.paper_status()` or, later, live balances), and recent
decision log entries with minimal code. If/when multi-user access or a
polished UI becomes a real requirement, wrap the core logic in FastAPI and
build a React frontend against it — the `kraken_ew` package's pure-function
design makes this wrapping straightforward later.

---

## Stock + options extension: Robinhood MCP bridge (built)

The system was extended to score equities/ETFs and trade single-leg options,
with two parallel data paths:

1. **Automated path (yfinance)**: `data/yfinance_client.py` +
   `live/stock_runner.py`, runnable headlessly via `kraken-ew stock-run` or a
   cron/scheduled task with no AI agent involved. This is what scheduled
   tasks should use, since they invoke the CLI as a plain subprocess.
2. **Live agent path (Robinhood MCP)**: MCP tools
   (`get_equity_historicals`, `get_option_chains`, `get_option_instruments`,
   `get_portfolio`, `get_option_positions`, `place_option_order`, etc.) are
   only callable by the AI agent *during a conversation turn* — they are not
   reachable from a standalone Python process. So real brokerage data is
   wired in via `scripts/score_from_bars.py`: the agent fetches bars from
   Robinhood, pipes them through this bridge script (which runs the exact
   same `kraken_ew.scoring.composite.compute_score`), and gets back a
   `ScoreBreakdown`. For signals, the agent calls `get_option_chains` /
   `get_option_instruments` directly for contract selection instead of
   `options/chain.py`'s yfinance-backed version.

**Why two paths instead of one**: there's no way to give a background
script its own authenticated MCP session — MCP credentials are scoped to
the interactive agent. Unifying them would require either (a) Robinhood
issuing a personal API token the script could call directly (not offered
today), or (b) running every scheduled scan as an agent turn (defeats the
purpose of a lightweight cron job). The two-path design is the practical
compromise: cheap automated scans on free data, accurate live data when a
human is in the loop and might actually trade.

**Observed data discrepancy** (worth tracking): scoring the same 5 tickers
from yfinance vs. Robinhood historicals on the same day produced different
wave counts and scores (e.g. SPY: yfinance scored 55.4/short, Robinhood
scored 36.7/long) — likely due to split/dividend-adjustment defaults and a
1-day difference in the most recent bar. This is a reminder that the
ZigZag-pivot-based wave detection is sensitive to the exact OHLCV series
used, which is itself a falsification-relevant data point: a strategy whose
signal flips direction based on adjustment methodology is fragile and
warrants caution before sizing real trades on it.

**Real-money guardrail**: `place_option_order`/`review_option_order` are
real and will place live trades on the user's Robinhood account when
called. Per the live-trading constraint established for the whole project,
these are only ever called with the user's explicit per-trade confirmation
— never autonomously from a scan or scheduled task.

---

## Phase 4 (designed, explicitly deferred): live execution + production infra

**This phase requires separate, explicit user approval before any code is
written** — it involves real money.

### Live execution
The Kraken CLI is already installed and MCP-registered with full scope
(`kraken mcp -s all`), exposing `kraken_order_buy` / `kraken_order_sell` /
`kraken_balance` / `kraken_positions` etc. In "guarded" mode, these require
`"acknowledged": true` per call. The natural design is:
- Reuse the exact same `scoring/composite.py` + `decisionlog/logger.py`
  pipeline from Phase 1.
- Replace `live/kraken_paper_cli.py` with a `live/kraken_live_cli.py` (or
  extend the existing module with a `--live` flag) that calls
  `kraken_order_buy`/`kraken_order_sell` instead of `kraken paper buy/sell`.
- Add the circuit breakers from `config/risk.yaml`
  (`max_daily_drawdown_pct`, etc.) as hard gates checked *before* every live
  order — if breached, the runner should refuse to trade and alert rather
  than silently stopping.
- A human-in-the-loop confirmation step (e.g., the agent proposes a trade via
  conversational MCP tool calls with `acknowledged: true` only after explicit
  user sign-off) is recommended for at least the first weeks of live
  operation, even after extensive paper trading.

### Database migration: DuckDB → PostgreSQL/TimescaleDB
Triggers for migration: multiple concurrent readers/writers (e.g. a
dashboard + live runner + backtest jobs all hitting the DB at once), need for
continuous-aggregate views (TimescaleDB) for dashboard performance, or data
volumes that make DuckDB's single-file model awkward (e.g. tick-level data
across many pairs/exchanges). The `ohlcv_store` module's interface
(`connect`, `upsert_ohlcv`, `read_ohlcv`) is intentionally narrow so swapping
the implementation (DuckDB → Postgres via SQLAlchemy/psycopg) shouldn't
require changes elsewhere in `kraken_ew`.

### Deployment / cloud architecture (sketch)
- Containerize the `kraken_ew` package (single Dockerfile).
- Scheduled jobs (e.g. cron or a lightweight scheduler) for: hourly data
  refresh, hourly scoring/paper-or-live runner, daily backtest re-run for
  monitoring drift.
- Persistent volume for DuckDB/Postgres data and `logs/decisions/`.
- Secrets (Kraken API key/secret for Phase 4) via the deployment platform's
  secret manager — never committed, never logged (the Kraken CLI already
  guarantees this for its own credential handling).
- Dashboard (Phase 3) deployed separately, read-only access to the
  database/decision logs.
