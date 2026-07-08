"""DuckDB-backed trade tracking: assessed/opened trades with entry, stop,
take-profit levels, and eventual close/outcome. Lives in the same
kraken_ew.duckdb file as the ohlcv table (see ohlcv_store.py).

This is NOT the Kraken paper ledger (kraken paper buy/sell) -- it's a
lightweight record of what the dashboard/scanner assessed and what actually
happened, independent of whether a paper or real order was ever placed. It
exists so the dashboard can show "trades we called" alongside their levels
and status, including manual trades the user places outside the system
(e.g. the CFG/SOL trades from this session).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import pandas as pd

from kraken_ew.data.ohlcv_store import DEFAULT_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,          -- 'long' or 'short'
    status TEXT NOT NULL,             -- 'open' or 'closed'
    entry_price DOUBLE NOT NULL,
    stop_price DOUBLE,
    tp1_price DOUBLE,
    tp2_price DOUBLE,
    tp3_price DOUBLE,
    volume DOUBLE,                    -- units of the asset
    score DOUBLE,                     -- composite score at entry
    opened_at TIMESTAMP NOT NULL,
    exit_price DOUBLE,
    closed_at TIMESTAMP,
    pnl_pct DOUBLE,
    notes TEXT
)
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    return con


def open_trade(
    con: duckdb.DuckDBPyConnection,
    pair: str,
    direction: str,
    entry_price: float,
    stop_price: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    tp3_price: float | None = None,
    volume: float | None = None,
    score: float | None = None,
    opened_at: pd.Timestamp | None = None,
    notes: str | None = None,
) -> str:
    """Record a new open trade. Returns the generated trade_id."""
    trade_id = str(uuid.uuid4())[:8]
    opened_at = opened_at or pd.Timestamp.utcnow()
    con.execute(
        """
        INSERT INTO trades (trade_id, pair, direction, status, entry_price,
            stop_price, tp1_price, tp2_price, tp3_price, volume, score,
            opened_at, notes)
        VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            trade_id, pair, direction, entry_price, stop_price,
            tp1_price, tp2_price, tp3_price, volume, score,
            opened_at, notes,
        ],
    )
    return trade_id


def close_trade(
    con: duckdb.DuckDBPyConnection,
    trade_id: str,
    exit_price: float,
    closed_at: pd.Timestamp | None = None,
    notes: str | None = None,
) -> None:
    """Mark a trade closed, computing pnl_pct from entry_price/direction."""
    row = con.execute(
        "SELECT entry_price, direction, notes FROM trades WHERE trade_id = ?", [trade_id]
    ).fetchone()
    if row is None:
        raise ValueError(f"no trade with id {trade_id}")
    entry_price, direction, existing_notes = row
    sign = 1 if direction == "long" else -1
    pnl_pct = sign * (exit_price / entry_price - 1) * 100
    closed_at = closed_at or pd.Timestamp.utcnow()
    merged_notes = existing_notes if not notes else f"{existing_notes or ''} {notes}".strip()
    con.execute(
        """
        UPDATE trades
        SET status = 'closed', exit_price = ?, closed_at = ?, pnl_pct = ?, notes = ?
        WHERE trade_id = ?
        """,
        [exit_price, closed_at, pnl_pct, merged_notes, trade_id],
    )


def list_trades(con: duckdb.DuckDBPyConnection, status: str | None = None) -> pd.DataFrame:
    """Return all trades, optionally filtered by status ('open'/'closed')."""
    if status:
        return con.execute(
            "SELECT * FROM trades WHERE status = ? ORDER BY opened_at DESC", [status]
        ).fetchdf()
    return con.execute("SELECT * FROM trades ORDER BY opened_at DESC").fetchdf()


def update_levels(
    con: duckdb.DuckDBPyConnection,
    trade_id: str,
    stop_price: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    tp3_price: float | None = None,
) -> None:
    """Update stop/TP levels on an existing trade (e.g. trailing a stop)."""
    fields, params = [], []
    for col, val in (
        ("stop_price", stop_price),
        ("tp1_price", tp1_price),
        ("tp2_price", tp2_price),
        ("tp3_price", tp3_price),
    ):
        if val is not None:
            fields.append(f"{col} = ?")
            params.append(val)
    if not fields:
        return
    params.append(trade_id)
    con.execute(f"UPDATE trades SET {', '.join(fields)} WHERE trade_id = ?", params)
