# Falsification Plan

Per the project's core constraint: **do not assume Elliott Wave works.**
This document defines how the EW composite strategy is compared against
simpler baselines, what would constitute evidence *against* the strategy,
and reports the Phase 1 MVP's initial results honestly.

## Baselines

1. **Buy & hold** — enter on bar 0, never exit. The "do nothing clever"
   floor.
2. **EMA crossover** (20/50) — classic trend-following. Cheap, well-known,
   no Elliott Wave required.
3. **Momentum (RSI)** — enter when RSI(14) crosses above 50, exit when it
   crosses back below. Cheap, well-known, no Elliott Wave required.
4. **EW composite** — this project's strategy: enter long/short when the
   composite score (wave validity + fib confluence + momentum + trend +
   volume + structure, weighted per `config/scoring_weights.yaml`) crosses
   `score_thresholds.long_entry` / `short_entry` (default 70) in the
   direction implied by the wave count; exit when the score drops below
   `score_thresholds.exit` (default 40).

## Kill criteria (defined *before* looking too hard at results)

The EW composite strategy should be considered **not worth pursuing further
in its current form** if, on out-of-sample data across multiple pairs:

- Its risk-adjusted return (Sharpe/Sortino/Calmar) is consistently *below*
  the best-performing simple baseline, **and**
- It does not produce a materially better max-drawdown profile to
  compensate, **and**
- It does not produce a meaningfully different (e.g. lower-frequency,
  higher-conviction) trade pattern that could justify lower returns via
  lower costs/effort.

If these hold, the honest conclusion is that the added complexity of wave
counting is not earning its keep, and either the scoring weights/thresholds
need fundamental rework (not just tuning) or the strategy should be
abandoned in favor of one of the baselines.

## Phase 1 MVP results

Data: Kraken daily candles, ~721 days (2024-06-25 to 2026-06-15), 0.26%
taker fee per trade, $10,000 initial cash. Generated via
`kraken-ew backtest --pairs XBTUSD,ETHUSD --interval 1440`.

### XBTUSD

| strategy | total_return_pct | sharpe | sortino | calmar | max_drawdown_pct | win_rate_pct | num_trades |
|---|---|---|---|---|---|---|---|
| ew_composite | 0.00 | n/a (no trades) | n/a | n/a | 0.00 | n/a | 0 |
| buy_and_hold | 5.95 | 0.29 | 0.43 | 0.06 | -51.22 | 100.00 | 1 |
| ema_crossover | 14.16 | 0.38 | 0.57 | 0.21 | -33.49 | 28.57 | 7 |
| momentum (RSI) | 16.22 | 0.41 | 0.61 | 0.29 | -27.57 | 23.33 | 30 |

### ETHUSD

| strategy | total_return_pct | sharpe | sortino | calmar | max_drawdown_pct | win_rate_pct | num_trades |
|---|---|---|---|---|---|---|---|
| ew_composite | -37.13 | -0.48 | -0.62 | -0.41 | -50.81 | 50.00 | 2 |
| buy_and_hold | -49.54 | -0.14 | -0.20 | -0.43 | -67.52 | 0.00 | 1 |
| ema_crossover | -2.10 | 0.17 | 0.26 | -0.03 | -32.93 | 22.22 | 9 |
| momentum (RSI) | 46.51 | 0.65 | 1.10 | 0.62 | -34.13 | 23.33 | 30 |

## Honest interpretation

**On this initial dataset, the EW composite strategy does not beat the
simple baselines, and in one case (ETHUSD) actively loses money while the
momentum baseline is strongly profitable.** Specifically:

- On **XBTUSD**, the composite score never crossed the 70-point entry
  threshold over the ~2-year window, so it took **zero trades** — a
  strategy that never trades cannot be evaluated on Sharpe/win-rate, and
  "never finding a setup" for 2 years on the most liquid crypto pair is
  itself informative: either the thresholds are too conservative, the
  weighting scheme rarely produces strong wave+confirmation alignment, or
  both.
- On **ETHUSD**, the composite took 2 trades and lost -37%, worse than
  buy & hold's -49.5% loss but far worse than the momentum baseline's +46.5%
  gain and the EMA crossover's roughly flat -2.1%.
- The **momentum (RSI) baseline is the standout performer on both pairs**
  (Sharpe 0.41 and 0.65), despite being the simplest strategy tested.

**This is a real signal against the current configuration**, per the kill
criteria above. However, before concluding "Elliott Wave doesn't work" at
all, note the following caveats specific to this MVP that should be
addressed first:

1. **Sample size is tiny.** 721 daily bars is roughly 2 years and only ~8
   major ZigZag swings at a 5% threshold — nowhere near enough wave-count
   instances to draw statistically meaningful conclusions about the wave
   scoring component specifically.
2. **Thresholds (70/40) were set as reasonable-looking defaults, not tuned.**
   The plan's own suggestion to backtest 70+/80+/90+ thresholds (and lower
   ones) has not yet been done. A threshold sweep is the immediate next
   experiment before any strategy-level conclusion.
3. **The composite score's "neutral" handling is aggressive**: when the wave
   count and trend direction don't agree (or there's no clear wave count),
   momentum/trend/volume/structure components are scored as 0, which can
   suppress the total score even when those individual signals are
   favorable. This may be too punitive and worth revisiting.
4. **Daily-only backtesting** misses the hourly-resolution scoring used in
   the live/paper runner — the live system may behave differently (more
   frequent re-evaluation) than this daily backtest suggests, in either
   direction.
5. **Only 2 of 5 target pairs tested** (SOLUSDT, AVAXUSDT, DOGEUSDT not yet
   backtested) — `kraken-ew fetch --pair <pair> --interval 1440` followed by
   `kraken-ew backtest --pairs <pairs>` extends this trivially.

## Update — deep-data, multi-timeframe & walk-forward results (2026-06)

After the initial Kraken-capped backtests above, we added the **Massive Market
Data** connector (`data/massive_rest.py`), which removes Kraken's ~720-candle
cap and provides deep daily, hourly, and 4-hour history. This let us re-run the
strategy across three timeframes and, critically, run a proper **walk-forward
consistency test** (`backtest/walk_forward.py`). The picture got much clearer.

### Same strategy, three timeframes (EW composite vs. baselines)

| Timeframe | Window | Sample | Verdict |
|---|---|---|---|
| Daily | 2 years (730 bars) | large | **Momentum wins, EW loses** (most trustworthy) |
| Hourly | ~35 days (833 bars) | medium | Everything active loses; EW defensive/near-flat |
| 4-hour | ~2.5 months (456 bars) | small | EW "wins" — but on 2–5 trades, overfit metrics |

The single biggest tell: **the momentum baseline completely inverts between
timeframes** — it's the best strategy on daily (+31% to +58%) and the worst on
hourly (-16% to -26%, whipsawed). That means most of these "strategies" are
really bets on whether the chosen timeframe trends or chops, not robust edges.

### The 4-hour result looked great — and was a trap

On a single 4h window (Apr–Jun 2026) the EW composite was best on all 3 pairs,
including **SOL +23.6% (Sharpe 4.09, Calmar 21.25)** while everything else lost.
Those risk metrics are not "great strategy" numbers — they are "lucky window /
overfit" numbers (2 trades, 100% win rate). So we tested it.

### Walk-forward: SOL 4h, 5 out-of-sample windows (Oct 2025 → Mar 2026)

A *separate* period from the window that produced the +23.6%:

| strategy | mean return | beats momentum | beats buy&hold | avg trades |
|---|---|---|---|---|
| **ew_composite** | **-1.43%** | **100%** | **100%** | 1.4 |
| ema_crossover | -16.93% | — | — | 5.2 |
| momentum | -23.64% | — | — | 20.8 |
| buy_and_hold | -30.91% | — | — | 1.0 |

Two firm conclusions:

1. **The +23.6% was not real.** Out of sample, SOL 4h EW composite averages
   **-1.4% (flat)**, not +23%. Walk-forward correctly deflated the overfit
   headline. *Do not build a thesis on a single good-looking backtest.*
2. **A genuine property did survive: defensiveness.** EW composite beat
   momentum and buy-and-hold in **100% of the 5 independent windows** by
   trading rarely (1.4 vs momentum's 20.8 trades) and sitting in cash through
   the chop. It never made money, but it reliably *lost the least*.

### Final characterization

**The EW composite is a capital-preservation filter, not an alpha generator.**
- It does **not** beat buy-and-hold in uptrends (daily/hourly).
- It does **not** produce positive returns out of sample (SOL 4h mean -1.4%).
- It **does** consistently avoid the bleed that kills active baselines in
  bearish/choppy conditions — robustly, across independent windows.

### Bull-market walk-forward — the test that completes the picture

The bear-market result above was run in isolation, so we re-ran the same
walk-forward on a SOL 4h **uptrend**: Apr–Oct 2025, +76% buy-and-hold,
5 windows.

| strategy | mean return | beats momentum | beats buy&hold | avg trades |
|---|---|---|---|---|
| **buy_and_hold** | **+19.47%** | — | — | 1.0 |
| ema_crossover | +7.62% | — | — | 4.6 |
| ew_composite | -3.66% | 80% | **0%** | 2.6 |
| momentum | -6.74% | — | — | 24.4 |

The EW composite **lost to buy-and-hold in 100% of bull windows**, sat in cash
in 2 of 5 (zero trades), and **missed the +76% rally entirely** (-3.66% mean).

### Two regimes side by side — the "defensive edge" hypothesis is FALSIFIED

| Regime | EW composite mean | buy & hold mean | what EW actually did |
|---|---|---|---|
| Bear (Oct25–Mar26) | **-1.4%** | -30.9% | "won" by default — others lost more |
| Bull (Apr–Oct25) | **-3.7%** | +19.5% | lost by default — missed the rally |

The unifying truth: **EW composite is flat-to-slightly-negative in *both*
regimes (-1.4% / -3.7%), almost independent of market direction, because it
barely trades.** Its bear-market out-performance was *non-participation*, not
protection. A genuine defensive overlay preserves capital in bears **and**
captures some upside in bulls; this one does neither. The only consistent
property is that it beats the **momentum** baseline — but only because momentum
self-destructs on 4h noise in every regime, and "loses less than the worst
strategy" is not an edge.

### Revised final verdict (both regimes tested — definitive)

The earlier "capital-preservation filter" framing was too generous. With the
bull-market test in, the conclusion is firmer: **the EW composite as configured
has no edge.** It is a near-flat, low-participation strategy that loses to
buy-and-hold in uptrends, merely loses-less (without real protection) in
downtrends, and only "beats" momentum because momentum is self-defeating on 4h.
It should **not** be pursued as a return-seeking strategy, and it does **not**
qualify as a usable defensive overlay either. If any part is salvageable, it is
individual *components* (e.g. the trend/volume confirmation), not the composite
score or the wave-validity core — which is the Phase 2 question, not a Phase 1
deliverable.

### Kill-criteria status

Per the kill criteria at the top of this document, the EW composite **has not
cleared the bar**: it does not beat the best simple baseline on risk-adjusted
return in the statistically trustworthy (daily, 2-year) test, and its
out-of-sample 4h returns are flat-to-negative in **both** bull and bear regimes.
The "defensive overlay" escape hatch has now been tested and **rejected**: in a
+76% bull market the strategy returned -3.7% (missed the rally), confirming its
near-zero return is non-participation, not protection. Recommended decision:
**do not pursue the composite as a standalone strategy or as a defensive
overlay.** Any further work should target individual components in Phase 2, not
the composite score as a whole.

## Recommended next falsification steps (before Phase 2)

0. ~~**Bull-market walk-forward**~~ — **DONE** (SOL 4h Apr–Oct 2025, +76% bull,
   5 windows). Result: EW composite -3.7% mean, lost to buy-and-hold in 100% of
   windows, missed the rally. This falsified the "defensive edge" hypothesis —
   see the two-regime section above. No longer open.
1. **Threshold sweep**: re-run the backtest across
   `long_entry/short_entry ∈ {50, 60, 70, 80, 90}` and
   `exit ∈ {30, 40, 50}` for all 5 pairs, to see whether *any* configuration
   of the current scoring model beats momentum, or whether the underlying
   signal (not just the threshold) is the problem.
2. **Component ablation**: re-run with each of the 6 weight components
   zeroed out one at a time (renormalizing the rest) to see which components
   are pulling the score in useful vs. unhelpful directions — this directly
   tests whether "wave_validity" (30% weight) is earning its outsized share.
3. **Run momentum and EMA-crossover baselines on hourly data too**, since
   that's the resolution the live system actually scores at — daily-only
   comparison may not be apples-to-apples with how the paper runner behaves.
4. Only after (1)-(3): decide whether to proceed to Phase 2 (ML evaluation)
   for the composite score, abandon wave-validity as a meaningful
   component, or revisit the wave-detection rules themselves
   (`waves/patterns.py`) as the root cause.
