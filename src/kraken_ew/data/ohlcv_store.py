"""DuckDB-backed OHLCV storage."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from kraken_ew.config import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "kraken_ew.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    pair TEXT NOT NULL,
    interval INTEGER NOT NULL,
    ts BIGINT NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    vwap DOUBLE NOT NULL,
    volume DOUBLE NOT NULL,
    trades INTEGER NOT NULL,
    PRIMARY KEY (pair, interval, ts)
)
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    return con


def upsert_ohlcv(con: duckdb.DuckDBPyConnection, pair: str, interval: int, rows: list[list]) -> int:
    """Insert OHLC rows (Kraken format: time, open, high, low, close, vwap, volume, count),
    skipping rows whose (pair, interval, ts) already exist. Returns count of rows inserted."""
    if not rows:
        return 0

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df = df.astype(
        {
            "time": "int64",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "vwap": "float64",
            "volume": "float64",
            "count": "int64",
        }
    )
    df.insert(0, "pair", pair)
    df.insert(1, "interval", interval)
    df = df.rename(columns={"time": "ts", "count": "trades"})
    df = df[["pair", "interval", "ts", "open", "high", "low", "close", "vwap", "volume", "trades"]]

    con.register("new_rows", df)
    before = con.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
    con.execute(
        """
        INSERT INTO ohlcv
        SELECT * FROM new_rows
        WHERE NOT EXISTS (
            SELECT 1 FROM ohlcv
            WHERE ohlcv.pair = new_rows.pair
              AND ohlcv.interval = new_rows.interval
              AND ohlcv.ts = new_rows.ts
        )
        """
    )
    after = con.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
    con.unregister("new_rows")
    return after - before


def read_ohlcv(con: duckdb.DuckDBPyConnection, pair: str, interval: int) -> pd.DataFrame:
    df = con.execute(
        "SELECT * FROM ohlcv WHERE pair = ? AND interval = ? ORDER BY ts",
        [pair, interval],
    ).fetchdf()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df


def find_gaps(con: duckdb.DuckDBPyConnection, pair: str, interval: int) -> pd.DataFrame:
    """Return rows where the gap to the next candle is larger than `interval` minutes."""
    df = read_ohlcv(con, pair, interval)
    if df.empty:
        return df
    expected_gap = interval * 60
    diffs = df["ts"].diff()
    gap_mask = diffs > expected_gap
    return df.loc[gap_mask, ["ts", "timestamp"]].assign(gap_seconds=diffs[gap_mask])
