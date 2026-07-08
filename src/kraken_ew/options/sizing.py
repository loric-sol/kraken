"""Position sizing for options trades.

Options sizing uses premium-at-risk (PAR): we risk a fixed % of portfolio
in premium paid — if the option goes to zero we lose that amount and no more.
This is different from stock/futures sizing where the stop-loss defines risk.
"""

from __future__ import annotations

import math

from kraken_ew.options.chain import SelectedContract


def size_position(
    contract: SelectedContract,
    portfolio_value: float,
    premium_risk_pct: float = 5.0,    # % of portfolio to risk in premium
    max_contracts: int = 10,
    max_position_pct: float = 25.0,   # hard cap on notional position size
) -> dict:
    """Return sizing info for *contract*.

    Each equity option contract covers 100 shares.
    Premium paid = contracts × mid × 100.
    Max loss = premium paid (buying options, not selling).
    """
    risk_budget = portfolio_value * premium_risk_pct / 100
    max_notional = portfolio_value * max_position_pct / 100
    cost_per_contract = contract.mid * 100  # 1 contract = 100 shares

    if cost_per_contract <= 0:
        return {"contracts": 0, "premium_total": 0.0, "risk_pct": 0.0}

    contracts = math.floor(risk_budget / cost_per_contract)
    contracts = max(0, min(contracts, max_contracts))

    # also respect max notional
    max_by_notional = math.floor(max_notional / cost_per_contract)
    contracts = min(contracts, max_by_notional)

    premium_total = contracts * cost_per_contract
    risk_pct = premium_total / portfolio_value * 100

    # profit/loss scenarios
    underlying_move_t1 = contract.greeks.delta * contract.strike * 0.01  # 1% move
    t1_premium = contract.mid + contract.greeks.delta * (contract.strike * 0.01)
    t2_premium = contract.mid + contract.greeks.delta * (contract.strike * 0.02)
    t3_premium = contract.mid + contract.greeks.delta * (contract.strike * 0.03)

    return {
        "contracts": contracts,
        "premium_per_contract": round(contract.mid, 4),
        "cost_per_contract": round(cost_per_contract, 2),
        "premium_total": round(premium_total, 2),
        "risk_pct": round(risk_pct, 2),
        "max_loss": round(premium_total, 2),
        "t1_pnl": round((t1_premium - contract.mid) * contracts * 100, 2),
        "t2_pnl": round((t2_premium - contract.mid) * contracts * 100, 2),
        "t3_pnl": round((t3_premium - contract.mid) * contracts * 100, 2),
    }
