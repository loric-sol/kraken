"""Rule-based Elliott Wave pattern matchers: 5-wave impulses and ABC corrections.

Each matcher takes the most recent pivots and checks them against the
classic Elliott Wave rules. Every violated rule reduces the confidence score
rather than disqualifying the count outright -- this is the "probabilistic
rather than deterministic" approach called for in the research doc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kraken_ew.waves.pivots import Pivot

VIOLATION_PENALTY = 35.0  # points deducted per hard-rule violation
SOFT_PENALTY = 15.0  # points deducted per soft/guideline violation


@dataclass
class WaveCount:
    label: Literal["impulse_5", "corrective_abc", "none"]
    pivots: list[Pivot] = field(default_factory=list)
    rule_violations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    direction: Literal["long", "short", "neutral"] = "neutral"


def _last_n_alternating(pivots: list[Pivot], n: int) -> list[Pivot] | None:
    """Return the last n pivots if they strictly alternate high/low/high/low..."""
    if len(pivots) < n:
        return None
    candidates = pivots[-n:]
    for a, b in zip(candidates, candidates[1:]):
        if a.kind == b.kind:
            return None
    return candidates


def match_impulse(pivots: list[Pivot]) -> WaveCount:
    """Check the last 6 pivots (P0..P5) for a 5-wave impulse structure.

    For an upward impulse: P0=low, P1=high, P2=low, P3=high, P4=low, P5=high
    (waves 1-5 are P0->P1, P1->P2, P2->P3, P3->P4, P4->P5).
    A downward impulse is the mirror image.
    """
    candidates = _last_n_alternating(pivots, 6)
    if candidates is None:
        return WaveCount(label="none", confidence=0.0)

    p0, p1, p2, p3, p4, p5 = candidates

    if p0.kind == "low" and p1.kind == "high":
        direction: Literal["long", "short"] = "long"
    elif p0.kind == "high" and p1.kind == "low":
        direction = "short"
    else:
        return WaveCount(label="none", confidence=0.0)

    wave1 = abs(p1.price - p0.price)
    wave2 = abs(p2.price - p1.price)
    wave3 = abs(p3.price - p2.price)
    wave4 = abs(p4.price - p3.price)
    wave5 = abs(p5.price - p4.price)

    violations: list[str] = []
    score = 100.0

    # Rule 1: wave 2 never retraces more than 100% of wave 1.
    if direction == "long" and p2.price <= p0.price:
        violations.append("wave2_retraces_beyond_wave1_start")
        score -= VIOLATION_PENALTY
    elif direction == "short" and p2.price >= p0.price:
        violations.append("wave2_retraces_beyond_wave1_start")
        score -= VIOLATION_PENALTY

    # Rule 2: wave 3 is never the shortest of waves 1, 3, 5.
    if wave3 < wave1 and wave3 < wave5:
        violations.append("wave3_is_shortest")
        score -= VIOLATION_PENALTY

    # Rule 3: wave 4 does not overlap wave 1's price territory (no overlap rule).
    # Allow as a soft violation since diagonals permit overlap (alternation principle).
    if direction == "long" and p4.price <= p1.price:
        violations.append("wave4_overlaps_wave1")
        score -= SOFT_PENALTY
    elif direction == "short" and p4.price >= p1.price:
        violations.append("wave4_overlaps_wave1")
        score -= SOFT_PENALTY

    # Guideline: wave 2 and wave 4 should alternate in form/depth (alternation
    # principle) -- approximate by checking they aren't near-identical retrace
    # percentages, which would suggest mislabeled pivots rather than alternation.
    wave2_retrace_pct = wave2 / wave1 if wave1 else 0
    wave4_retrace_pct = wave4 / wave3 if wave3 else 0
    if abs(wave2_retrace_pct - wave4_retrace_pct) < 0.05:
        violations.append("no_alternation_between_wave2_and_wave4")
        score -= SOFT_PENALTY

    score = max(0.0, score)
    return WaveCount(label="impulse_5", pivots=candidates, rule_violations=violations, confidence=score, direction=direction)


def match_corrective_abc(pivots: list[Pivot]) -> WaveCount:
    """Check the last 3 pivots (start, A, B... actually P_end_of_impulse, A, B, C)
    for an ABC corrective structure: a 3-pivot zigzag where:
      - B retraces 23.6%-78.6% of A
      - C relates to A via ~0.618, 1.0, or 1.618 (within tolerance)
    """
    candidates = _last_n_alternating(pivots, 4)
    if candidates is None:
        return WaveCount(label="none", confidence=0.0)

    start, a, b, c = candidates

    if start.kind == "high" and a.kind == "low":
        direction: Literal["long", "short"] = "long"  # correction down, expect reversal up
    elif start.kind == "low" and a.kind == "high":
        direction = "short"
    else:
        return WaveCount(label="none", confidence=0.0)

    wave_a = abs(a.price - start.price)
    wave_b = abs(b.price - a.price)
    wave_c = abs(c.price - b.price)

    violations: list[str] = []
    score = 100.0

    b_retrace_pct = wave_b / wave_a if wave_a else 0
    if not (0.236 <= b_retrace_pct <= 0.786):
        violations.append("b_retrace_outside_range")
        score -= VIOLATION_PENALTY

    c_to_a_ratio = wave_c / wave_a if wave_a else 0
    target_ratios = (0.618, 1.0, 1.618)
    if not any(abs(c_to_a_ratio - r) <= 0.15 for r in target_ratios):
        violations.append("c_not_near_fib_ratio_of_a")
        score -= SOFT_PENALTY

    # B should not retrace beyond the start of A (i.e. beyond `start`).
    if direction == "long" and b.price >= start.price:
        violations.append("b_exceeds_correction_start")
        score -= VIOLATION_PENALTY
    elif direction == "short" and b.price <= start.price:
        violations.append("b_exceeds_correction_start")
        score -= VIOLATION_PENALTY

    score = max(0.0, score)
    return WaveCount(label="corrective_abc", pivots=candidates, rule_violations=violations, confidence=score, direction=direction)


def best_wave_count(pivots: list[Pivot]) -> WaveCount:
    """Try both matchers and return the higher-confidence count."""
    impulse = match_impulse(pivots)
    abc = match_corrective_abc(pivots)
    if impulse.confidence >= abc.confidence:
        return impulse if impulse.label != "none" else abc
    return abc
