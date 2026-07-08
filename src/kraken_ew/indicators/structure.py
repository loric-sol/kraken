"""Market structure engine: HH/HL/LH/LL labeling, break of structure (BOS)
and change of character (CHoCH) detection.

This module operates on swing pivots (see kraken_ew.waves.pivots) rather than
raw bars, since "structure" is inherently a pivot-to-pivot concept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kraken_ew.waves.pivots import Pivot

StructureLabel = Literal["HH", "HL", "LH", "LL", "none"]


@dataclass
class StructureEvent:
    label: StructureLabel
    pivot: Pivot


def label_structure(pivots: list[Pivot]) -> list[StructureEvent]:
    """Label each pivot relative to the most recent prior pivot of the same kind
    (high vs low): HH/LH for highs, HL/LL for lows."""
    events: list[StructureEvent] = []
    last_high: Pivot | None = None
    last_low: Pivot | None = None

    for p in pivots:
        if p.kind == "high":
            if last_high is not None:
                label: StructureLabel = "HH" if p.price > last_high.price else "LH"
            else:
                label = "none"
            events.append(StructureEvent(label=label, pivot=p))
            last_high = p
        else:
            if last_low is not None:
                label = "HL" if p.price > last_low.price else "LL"
            else:
                label = "none"
            events.append(StructureEvent(label=label, pivot=p))
            last_low = p

    return events


@dataclass
class StructureBreak:
    kind: Literal["BOS_up", "BOS_down", "CHoCH_up", "CHoCH_down", "none"]


def detect_structure_break(events: list[StructureEvent]) -> StructureBreak:
    """Detect Break of Structure (continuation: e.g. another HH in an uptrend)
    vs Change of Character (reversal: e.g. first LL after a run of HH/HL).

    Looks at the last 4 labeled events to find the prevailing trend and
    whether the most recent event continues or breaks it.
    """
    labeled = [e for e in events if e.label != "none"]
    if len(labeled) < 3:
        return StructureBreak("none")

    recent = labeled[-4:]
    last = recent[-1]
    prior = recent[:-1]

    uptrend_votes = sum(1 for e in prior if e.label in ("HH", "HL"))
    downtrend_votes = sum(1 for e in prior if e.label in ("LH", "LL"))

    if uptrend_votes > downtrend_votes:
        if last.label in ("HH", "HL"):
            return StructureBreak("BOS_up")
        return StructureBreak("CHoCH_down")

    if downtrend_votes > uptrend_votes:
        if last.label in ("LH", "LL"):
            return StructureBreak("BOS_down")
        return StructureBreak("CHoCH_up")

    return StructureBreak("none")


def structure_score(pivots: list[Pivot], direction: Literal["long", "short"]) -> float:
    """0-100 score for the "market structure" composite component.

    Rewards BOS in `direction`'s favor highly, CHoCH in `direction`'s favor
    moderately (early reversal signal), and penalizes structure against
    `direction`.
    """
    events = label_structure(pivots)
    brk = detect_structure_break(events)

    favorable_bos = "BOS_up" if direction == "long" else "BOS_down"
    favorable_choch = "CHoCH_up" if direction == "long" else "CHoCH_down"
    unfavorable_bos = "BOS_down" if direction == "long" else "BOS_up"
    unfavorable_choch = "CHoCH_down" if direction == "long" else "CHoCH_up"

    if brk.kind == favorable_bos:
        return 100.0
    if brk.kind == favorable_choch:
        return 60.0
    if brk.kind == unfavorable_choch:
        return 30.0
    if brk.kind == unfavorable_bos:
        return 0.0
    return 50.0
