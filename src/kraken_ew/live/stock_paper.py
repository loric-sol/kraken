"""Simulated options paper trading — tracks open positions and P&L in DuckDB.

Since no broker offers a free options paper trading API (Robinhood's paper
trading doesn't support options), we simulate: record the entry premium,
fetch the current mid-market price each run, and compute mark-to-market P&L.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DB = Path(__file__).parents[4] / "data" / "stock_paper.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    option_type TEXT NOT NULL,
    expiry      TEXT NOT NULL,
    dte_entry   INTEGER,
    strike      DOUBLE,
    contracts   INTEGER,
    entry_mid   DOUBLE,
    entry_total DOUBLE,
    entry_time  TEXT,
    status      TEXT DEFAULT 'open',   -- open | closed
    exit_mid    DOUBLE,
    exit_total  DOUBLE,
    exit_time   TEXT,
    pnl         DOUBLE,
    pnl_pct     DOUBLE,
    score       DOUBLE,
    direction   TEXT,
    metadata    TEXT
);
CREATE SEQUENCE IF NOT EXISTS pos_id_seq START 1;
"""


def connect(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    path = db_path or DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con


def open_position(
    con: duckdb.DuckDBPyConnection,
    ticker: str,
    option_type: str,
    expiry: str,
    dte: int,
    strike: float,
    contracts: int,
    entry_mid: float,
    score: float,
    direction: str,
    metadata: dict | None = None,
) -> int:
    entry_total = round(contracts * entry_mid * 100, 2)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """INSERT INTO positions
           (id, ticker, option_type, expiry, dte_entry, strike, contracts,
            entry_mid, entry_total, entry_time, score, direction, metadata)
           VALUES (nextval('pos_id_seq'),?,?,?,?,?,?,?,?,?,?,?,?)""",
        [ticker, option_type, expiry, dte, strike, contracts,
         entry_mid, entry_total, now, score, direction,
         json.dumps(metadata or {})],
    )
    row = con.execute("SELECT max(id) FROM positions").fetchone()
    return row[0]


def close_position(
    con: duckdb.DuckDBPyConnection,
    position_id: int,
    exit_mid: float,
) -> dict:
    pos = con.execute(
        "SELECT * FROM positions WHERE id=?", [position_id]
    ).fetchdf().iloc[0]
    exit_total = round(int(pos["contracts"]) * exit_mid * 100, 2)
    pnl = round(exit_total - float(pos["entry_total"]), 2)
    pnl_pct = round(pnl / float(pos["entry_total"]) * 100, 2) if pos["entry_total"] else 0.0
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        """UPDATE positions SET status='closed', exit_mid=?, exit_total=?,
           exit_time=?, pnl=?, pnl_pct=? WHERE id=?""",
        [exit_mid, exit_total, now, pnl, pnl_pct, position_id],
    )
    return {"pnl": pnl, "pnl_pct": pnl_pct, "exit_total": exit_total}


def open_positions(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM positions WHERE status='open'").fetchdf()


def all_positions(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("SELECT * FROM positions ORDER BY id").fetchdf()


def portfolio_summary(con: duckdb.DuckDBPyConnection, starting_cash: float = 10_000.0) -> dict:
    df = all_positions(con)
    if df.empty:
        return {"starting": starting_cash, "realized_pnl": 0.0,
                "open_premium_at_risk": 0.0, "open_premium": 0.0,
                "cash_remaining": starting_cash, "total_return_pct": 0.0,
                "num_trades": 0, "open_positions": 0}
    realized = float(df[df["status"] == "closed"]["pnl"].sum()) if not df[df["status"]=="closed"].empty else 0.0
    open_cost = float(df[df["status"] == "open"]["entry_total"].sum()) if not df[df["status"]=="open"].empty else 0.0
    current_value = starting_cash + realized - open_cost  # cash remaining + realized gains
    return {
        "starting": starting_cash,
        "realized_pnl": round(realized, 2),
        "open_premium_at_risk": round(open_cost, 2),
        "open_premium": round(open_cost, 2),
        "cash_remaining": round(current_value, 2),
        "total_return_pct": round(realized / starting_cash * 100, 2),
        "num_trades": len(df),
        "open_positions": int((df["status"] == "open").sum()),
    }
