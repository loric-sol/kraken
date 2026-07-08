"""Subprocess wrapper around the `kraken paper ...` CLI commands.

Reuses Kraken CLI's own paper-trading ledger (run `kraken paper init` once)
rather than reimplementing paper portfolio accounting.
"""

from __future__ import annotations

import json
import subprocess

KRAKEN_BIN = "kraken"


class KrakenCLIError(RuntimeError):
    pass


def _run(args: list[str]) -> dict:
    result = subprocess.run([KRAKEN_BIN, *args, "-o", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        raise KrakenCLIError(f"kraken {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise KrakenCLIError(f"could not parse kraken output as JSON: {result.stdout!r}") from exc


def paper_status() -> dict:
    return _run(["paper", "status"])


def paper_balance() -> dict:
    return _run(["paper", "balance"])


def paper_orders() -> dict:
    return _run(["paper", "orders"])


def paper_buy(pair: str, volume: float, order_type: str = "market") -> dict:
    return _run(["paper", "buy", pair, str(volume), "--type", order_type])


def paper_sell(pair: str, volume: float, order_type: str = "market") -> dict:
    return _run(["paper", "sell", pair, str(volume), "--type", order_type])
