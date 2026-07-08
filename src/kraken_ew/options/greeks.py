"""Black-Scholes Greeks calculation via mibian."""

from __future__ import annotations

from dataclasses import dataclass

import mibian


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float  # per day
    vega: float   # per 1% IV move
    iv: float     # implied volatility (decimal)
    option_type: str  # 'call' or 'put'


def calculate_greeks(
    spot: float,
    strike: float,
    dte: int,
    iv: float,         # implied volatility as decimal (e.g. 0.30 = 30%)
    risk_free: float,  # annualized risk-free rate as decimal
    option_type: str,  # 'call' or 'put'
) -> Greeks:
    """Compute Black-Scholes Greeks for a European option.

    mibian expects IV as a percentage (30.0, not 0.30).
    """
    iv_pct = iv * 100
    rf_pct = risk_free * 100
    t = max(dte / 365, 1 / 365)  # avoid zero-time edge case

    bs = mibian.BS([spot, strike, rf_pct, dte], volatility=iv_pct)

    if option_type == "call":
        delta = bs.callDelta
        theta = bs.callTheta
    else:
        delta = bs.putDelta
        theta = bs.putTheta

    return Greeks(
        delta=delta,
        gamma=bs.gamma,
        theta=theta / 365,  # mibian returns annualized theta; convert to daily
        vega=bs.vega / 100,  # per 1% IV move
        iv=iv,
        option_type=option_type,
    )
