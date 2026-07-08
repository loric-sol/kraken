"""Select the best option contract for a given directional signal."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from kraken_ew.options.greeks import Greeks, calculate_greeks


@dataclass
class SelectedContract:
    ticker: str
    option_type: str       # 'call' or 'put'
    expiry: str            # 'YYYY-MM-DD'
    dte: int
    strike: float
    mid: float             # mid-market premium (per share)
    bid: float
    ask: float
    iv: float
    greeks: Greeks
    open_interest: int
    volume: int


def select_contract(
    ticker: str,
    chain: pd.DataFrame,
    direction: str,        # 'long' → calls, 'short' → puts
    spot: float,
    delta_target: float = 0.45,
    delta_tolerance: float = 0.10,
    risk_free: float = 0.05,
) -> SelectedContract | None:
    """Pick the best contract from *chain* for *direction*.

    Selection criteria (in order):
    1. Filter to correct option type (calls for long, puts for short)
    2. Filter to contracts with non-zero bid and reasonable spread
    3. Compute delta for each candidate via Black-Scholes
    4. Pick the contract whose delta is closest to delta_target
    """
    if chain.empty:
        return None

    opt_type = "call" if direction == "long" else "put"
    candidates = chain[chain["option_type"] == opt_type].copy()
    candidates = candidates[candidates["bid"] > 0]
    candidates = candidates[candidates["mid"] > 0]
    # remove contracts with spread > 20% of mid (illiquid)
    candidates = candidates[(candidates["ask"] - candidates["bid"]) / candidates["mid"] < 0.20]

    if candidates.empty:
        return None

    best = None
    best_delta_diff = float("inf")

    for _, row in candidates.iterrows():
        iv = float(row.get("impliedVolatility", 0.30))
        if iv <= 0:
            iv = 0.30  # fallback if chain doesn't provide IV

        greeks = calculate_greeks(
            spot=spot,
            strike=float(row["strike"]),
            dte=int(row["dte"]),
            iv=iv,
            risk_free=risk_free,
            option_type=opt_type,
        )
        delta = abs(greeks.delta)  # puts have negative delta; compare magnitude
        diff = abs(delta - delta_target)

        if diff < best_delta_diff and (delta_target - delta_tolerance) <= delta <= (delta_target + delta_tolerance):
            best_delta_diff = diff
            best = SelectedContract(
                ticker=ticker,
                option_type=opt_type,
                expiry=str(row["expiry"]),
                dte=int(row["dte"]),
                strike=float(row["strike"]),
                mid=float(row["mid"]),
                bid=float(row["bid"]),
                ask=float(row["ask"]),
                iv=iv,
                greeks=greeks,
                open_interest=int(row.get("openInterest", 0)),
                volume=int(row.get("volume", 0)),
            )

    return best
