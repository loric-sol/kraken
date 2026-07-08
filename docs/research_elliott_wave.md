# Research: Elliott Wave Theory → Code

This document explains the core Elliott Wave Theory (EWT) concepts the
system uses, and exactly how each one is implemented as objective, testable
code in `src/kraken_ew/waves/` and `src/kraken_ew/indicators/`. The guiding
principle (per the project brief) is: **if a concept can't be measured,
scored, or tested, it gets redesigned or dropped.**

## 1. The basic pattern: impulse + correction

Classic EWT says markets move in a 5-wave "impulse" in the direction of the
larger trend, followed by a 3-wave "correction" (commonly labeled A-B-C)
against it. This 5+3 = 8-wave cycle is the fractal unit that (in theory)
repeats at every timeframe.

**Code mapping:**
- `waves/pivots.py` — `zigzag_pivots()` reduces a price series to its
  significant swing highs/lows (a configurable % threshold, default 5%).
  This is the raw material every wave count is built from. `fractal_pivots()`
  provides a finer-grained secondary pivot source (Williams fractals) that
  could be used for confluence in a future iteration.
- `waves/patterns.py` — `match_impulse()` takes the last 6 pivots and checks
  them against impulse rules; `match_corrective_abc()` takes the last 4
  pivots and checks ABC rules. Both return a `WaveCount` with a 0-100
  `confidence` score derived from rule compliance, not a binary "is this an
  impulse?" verdict.
- `waves/wave_validity.py` — picks whichever of impulse/ABC scores higher and
  reports it as the "wave structure validity" score (30% of the composite,
  see `config/scoring_weights.yaml`).

## 2. Impulse wave rules (objective, hard-coded)

The three rules EWT treats as inviolable for a valid impulse:

1. **Wave 2 never retraces more than 100% of wave 1.** If it does, the
   structure isn't an impulse at all.
2. **Wave 3 is never the shortest of waves 1, 3, and 5.** Wave 3 is usually
   the longest and strongest.
3. **Wave 4 does not enter wave 1's price territory** (the "no overlap"
   rule) — *except* in a small subset of patterns (diagonals), where overlap
   is allowed.

**Code mapping** (`match_impulse` in `waves/patterns.py`):
- Rules 1 and 2 are treated as **hard violations** (`VIOLATION_PENALTY = 35`
  points each).
- Rule 3 is treated as a **soft violation** (`SOFT_PENALTY = 15` points),
  because diagonals are a legitimate (if less common) exception — this is
  exactly the kind of "subjective exception" the system converts into a
  *quantified* penalty rather than a binary disqualification.

## 3. Corrective waves (ABC)

A simple zigzag correction is A-B-C, where:
- B retraces some portion of A (commonly 23.6%-78.6%)
- C tends to relate to A by a Fibonacci ratio (0.618, 1.0, or 1.618×)
- B should not retrace beyond the start of the move that preceded A

**Code mapping** (`match_corrective_abc` in `waves/patterns.py`):
- B's retrace percentage outside [0.236, 0.786] → hard violation.
- C/A ratio not within ±0.15 of {0.618, 1.0, 1.618} → soft violation.
- B exceeding the pre-correction start → hard violation.

## 4. Fractals

EWT claims the impulse/correction pattern repeats at every timeframe — a
wave 1 on a daily chart is itself a 5-wave impulse on an hourly chart.

**Code mapping:** Phase 1 does **not** implement multi-timeframe recursive
wave counting (this is one of the largest sources of EWT subjectivity in
practice, since "which timeframe is the relevant one" is itself a judgment
call). Instead, the system runs the same wave-detection logic independently
on whatever interval is configured (daily for backtesting, hourly for live
scoring). True fractal/multi-timeframe confluence is listed as a Phase 3+
research item in `docs/roadmap.md`.

## 5. Extensions and truncations

- **Extension**: one of the three impulse waves (usually wave 3, sometimes 1
  or 5) is unusually long relative to the others.
- **Truncation**: wave 5 fails to exceed the end of wave 3 (a recognized but
  relatively rare exception to the "wave 5 makes a new extreme" expectation).

**Code mapping:** Phase 1 does not explicitly detect extensions or
truncations as named patterns. They are implicitly handled by the
confidence-scoring approach: an extended wave 3 simply produces a high
"wave 3 is not the shortest" pass rate (it's *definitely* not the shortest),
and a truncated wave 5 would show up as an unusually short wave 5 relative to
wave 1/3, which the alternation/relative-length checks partially capture.
Explicit extension/truncation classifiers are a Phase 2+ enhancement.

## 6. The alternation principle

EWT's alternation guideline says wave 2 and wave 4 (within an impulse) tend
to differ in *form* — if wave 2 is a sharp, fast correction, wave 4 tends to
be a sideways, time-consuming one (and vice versa).

**Code mapping:** Phase 1 approximates this narrowly: it compares wave 2's
retrace percentage of wave 1 to wave 4's retrace percentage of wave 3. If
they're nearly identical (within 5 percentage points), that's flagged as
`no_alternation_between_wave2_and_wave4` (a soft violation) — the intuition
being that *genuinely* alternating waves shouldn't look like near-identical
retracements. This is a coarse proxy, not a full implementation of
alternation (which properly concerns *shape*, e.g. zigzag vs. flat vs.
triangle, not just depth).

## 7. Fibonacci relationships

EWT pairs naturally with Fibonacci ratios for retracement depths and
extension targets.

**Code mapping** (`waves/fibonacci.py`):
- `retracement_levels()` computes standard retracement levels (23.6%, 38.2%,
  50%, 61.8%, 78.6%) of a given pivot-to-pivot swing.
- `extension_levels()` projects extension levels (127.2%, 161.8%, 200%,
  261.8%) from a retracement pivot, sized by a prior swing.
- `confluence_score()` checks how many *independent* level sets cluster
  within a tolerance band (default 0.5%) of the current price — true
  Fibonacci confluence requires multiple independent measurements to agree,
  not just "the price is near *a* fib level" (which is nearly always true of
  *some* level).

In the composite score (`scoring/composite.py`), `_fib_confluence()` builds
two level sets from the most recent pivots (a retracement set and an
extension set) and scores their agreement with the current price. This is
intentionally minimal for Phase 1 — a richer confluence engine (more pivot
combinations, multiple timeframes) is a natural Phase 2 enhancement.

## 8. From subjective to probabilistic

The single most important design decision in this system is captured by
`WaveCount.confidence`: **every wave count is a number between 0 and 100, not
a yes/no answer.** This number feeds into the composite score
(`scoring/composite.py`) alongside independent confirmation from trend,
momentum, volume, volatility, and market structure — so even a "perfect" wave
count contributes only 30% of the final decision, and a flawed-but-plausible
count can still contribute meaningfully if every other signal lines up.

This is the system's answer to "Elliott Wave is too subjective": it doesn't
claim to resolve the subjectivity of *which* count is "correct" — instead it
quantifies *how compliant* a given count is with EWT's own rules, and forces
that quantification to compete with, and be checked against, independent
quantitative signals. `docs/falsification_plan.md` describes how we test
whether this actually adds value over simpler strategies.
