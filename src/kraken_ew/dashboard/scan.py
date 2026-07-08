"""Shared scan logic for the basket scanner and the multi-timeframe
(1D/4H/1H) assessment used throughout live analysis. Consolidates what was
previously ad-hoc scripting into one reusable, importable module used by
both the Streamlit dashboard and the scheduled scanner task.

Two entry points:
- scan_basket(pairs): hourly composite score across a list of pairs, with
  momentum/MACD/OBV context. This is the "what's worth watching" screen.
- multi_timeframe(pair): full 1D/4H/1H synthesis for a single pair, plus an
  ATR-based trade plan (hourly stop, daily-ATR targets). This is the
  "assess this one pair properly" view used for entries and open positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from kraken_ew.config import AppConfig
from kraken_ew.data import kraken_rest, ohlcv_store
from kraken_ew.indicators.momentum import add_momentum
from kraken_ew.indicators.volatility import atr
from kraken_ew.indicators.volume import add_volume
from kraken_ew.scoring.composite import ScoreBreakdown, compute_score

DEFAULT_BASKET = [
    "XBTUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "XDGUSD",
    "LINKUSD", "DOTUSD", "ADAUSD", "XXRPZUSD", "UNIUSD",
    "ATOMUSD", "NEARUSD", "ARBUSD", "OPUSD", "SUIUSD",
    "APTUSD", "INJUSD", "XLMUSD", "CFGUSD", "JUPUSD",
]

PRIORITY_WATCHLIST = ["SOLUSD", "DOTUSD"]

TIER_SIGNAL = 70.0
TIER_APPROACHING = 65.0
TIER_PRIORITY = 60.0


@dataclass
class BasketRow:
    pair: str
    price: float
    score: float
    direction: str
    rsi: float
    macd_bull: bool
    obv_rising: bool
    tier: str  # "", "priority", "approaching", "signal"


@dataclass
class TimeframeRead:
    timeframe: str  # "1D", "4H", "1H"
    score: float
    direction: str
    rsi: float
    rsi_prev: float
    macd_bull: bool
    atr_value: float


@dataclass
class TradePlan:
    pair: str
    direction: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    position_value: float
    risk_usd: float


@dataclass
class MultiTimeframeAssessment:
    pair: str
    price: float
    daily: TimeframeRead
    four_hour: TimeframeRead
    hourly: TimeframeRead
    trade_plan: TradePlan | None = None


def _tier_for(pair: str, score: float, direction: str) -> str:
    if direction != "long":
        return ""
    if score >= TIER_SIGNAL:
        return "signal"
    if score >= TIER_APPROACHING:
        return "approaching"
    if pair in PRIORITY_WATCHLIST and score >= TIER_PRIORITY:
        return "priority"
    return ""


def scan_basket(
    con,
    config: AppConfig,
    pairs: list[str] | None = None,
    fetch: bool = True,
) -> list[BasketRow]:
    """Score every pair in `pairs` (default DEFAULT_BASKET) on hourly data.
    If `fetch` is True, pulls fresh candles from Kraken first; set False to
    score whatever is already in the local DuckDB store (faster, offline)."""
    pairs = pairs or DEFAULT_BASKET
    rows: list[BasketRow] = []

    for pair in pairs:
        if fetch:
            try:
                candles, _ = kraken_rest.get_ohlc(pair, interval=60)
                ohlcv_store.upsert_ohlcv(con, pair, 60, candles)
            except Exception:
                continue

        df = ohlcv_store.read_ohlcv(con, pair, 60)
        if df.empty or len(df) < 60:
            continue

        bd = compute_score(df, pair, config.scoring)
        dm = add_momentum(df.copy())
        dv = add_volume(df.copy())

        price = float(df["close"].iloc[-1])
        rsi = float(dm["rsi"].iloc[-1])
        macd_bull = bool(dm["macd"].iloc[-1] > dm["macd_signal"].iloc[-1])
        obv_rising = bool(dv["obv"].iloc[-1] > dv["obv"].iloc[-6])

        rows.append(
            BasketRow(
                pair=pair,
                price=price,
                score=bd.total,
                direction=bd.direction,
                rsi=rsi,
                macd_bull=macd_bull,
                obv_rising=obv_rising,
                tier=_tier_for(pair, bd.total, bd.direction),
            )
        )

    rows.sort(key=lambda r: -r.score)
    return rows


def _resample_4h(df_hourly: pd.DataFrame) -> pd.DataFrame:
    df4 = (
        df_hourly.set_index("timestamp")
        .resample("4h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )
    df4["ts"] = df4["timestamp"].astype("int64") // 10**9
    return df4


def _timeframe_read(label: str, df: pd.DataFrame, pair: str, config: AppConfig) -> TimeframeRead:
    bd = compute_score(df, pair, config.scoring)
    dm = add_momentum(df.copy())
    atr_value = float(atr(df, period=14).iloc[-1])
    return TimeframeRead(
        timeframe=label,
        score=bd.total,
        direction=bd.direction,
        rsi=float(dm["rsi"].iloc[-1]),
        rsi_prev=float(dm["rsi"].iloc[-2]),
        macd_bull=bool(dm["macd"].iloc[-1] > dm["macd_signal"].iloc[-1]),
        atr_value=atr_value,
    )


def build_trade_plan(
    pair: str,
    direction: str,
    entry: float,
    hourly_atr: float,
    daily_atr: float,
    config: AppConfig,
    account_value: float = 10_000.0,
) -> TradePlan:
    """Tight hourly-ATR stop (entry timing), daily-ATR-sized targets (trend
    scale) -- the approach established during live SOL/CFG analysis: stops
    reflect short-term noise, targets reflect the higher-timeframe trend."""
    risk = config.risk
    stop_dist = hourly_atr * risk.stop_loss["atr_multiplier"]
    sign = 1 if direction == "long" else -1

    risk_usd_target = account_value * risk.position_sizing["risk_per_trade_pct"] / 100
    max_position = account_value * risk.position_sizing["max_position_pct"] / 100
    position_value = min(risk_usd_target / (stop_dist / entry), max_position) if stop_dist > 0 else 0.0
    units = position_value / entry if entry > 0 else 0.0
    risk_usd = units * stop_dist

    stop = entry - sign * stop_dist
    tp1 = entry + sign * daily_atr
    tp2 = entry + sign * 2 * daily_atr
    tp3 = entry + sign * 3 * daily_atr

    return TradePlan(
        pair=pair, direction=direction, entry=entry, stop=stop,
        tp1=tp1, tp2=tp2, tp3=tp3,
        position_value=position_value, risk_usd=risk_usd,
    )


def multi_timeframe(
    con,
    config: AppConfig,
    pair: str,
    fetch: bool = True,
    account_value: float = 10_000.0,
) -> MultiTimeframeAssessment:
    """Full 1D/4H/1H synthesis for a single pair, plus a trade plan sized
    off the composite direction's higher-score timeframe (prefers hourly
    direction since that's the trigger timeframe, matching prior analysis)."""
    if fetch:
        rows_h, _ = kraken_rest.get_ohlc(pair, interval=60)
        ohlcv_store.upsert_ohlcv(con, pair, 60, rows_h)
        rows_d, _ = kraken_rest.get_ohlc(pair, interval=1440)
        ohlcv_store.upsert_ohlcv(con, pair, 1440, rows_d)

    df_h = ohlcv_store.read_ohlcv(con, pair, 60)
    df_d = ohlcv_store.read_ohlcv(con, pair, 1440)
    df_4 = _resample_4h(df_h)

    price = float(df_h["close"].iloc[-1])
    daily = _timeframe_read("1D", df_d, pair, config)
    four_hour = _timeframe_read("4H", df_4, pair, config)
    hourly = _timeframe_read("1H", df_h, pair, config)

    trade_plan = None
    if hourly.direction in ("long", "short"):
        trade_plan = build_trade_plan(
            pair, hourly.direction, price,
            hourly_atr=hourly.atr_value, daily_atr=daily.atr_value,
            config=config, account_value=account_value,
        )

    return MultiTimeframeAssessment(
        pair=pair, price=price, daily=daily, four_hour=four_hour, hourly=hourly,
        trade_plan=trade_plan,
    )
