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
from kraken_ew.indicators.momentum import add_momentum, momentum_direction
from kraken_ew.indicators.volatility import atr
from kraken_ew.indicators.volume import add_volume
from kraken_ew.scoring.composite import ScoreBreakdown, compute_score

DEFAULT_BASKET = [
    "XBTUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "XDGUSD",
    "LINKUSD", "DOTUSD", "ADAUSD", "XXRPZUSD", "UNIUSD",
    "ATOMUSD", "NEARUSD", "ARBUSD", "OPUSD", "SUIUSD",
    "APTUSD", "INJUSD", "XLMUSD", "CFGUSD", "JUPUSD",
    "PENGUUSD", "MORPHOUSD", "AEROUSD", "SYRUPUSD", "XPLUSD",
    "PYTHUSD", "HYPEUSD",
]

# Kraken uses ISO-style asset codes (XBT, XDG, XXRPZ) for a couple of pairs;
# display the common ticker instead everywhere in the UI.
DISPLAY_LABEL = {"XDGUSD": "DOGE", "XXRPZUSD": "XRP", "XBTUSD": "BTC"}

# Pairs whose wave counts have repeatedly shown rule violations on every
# timeframe checked -- still scanned normally, but flagged as low-confidence
# rather than trusted at face value.
LOW_WAVE_CONFIDENCE = {"MORPHOUSD", "AEROUSD", "SYRUPUSD"}

PRIORITY_WATCHLIST = ["SOLUSD", "DOTUSD", "XPLUSD", "HYPEUSD", "ARBUSD"]

TIER_SIGNAL = 70.0
TIER_APPROACHING = 65.0
TIER_PRIORITY = 60.0

# A pair whose DAILY RSI jumps more than this many points vs. the prior
# daily bar gets flagged regardless of hourly score -- added after ARBUSD's
# 39->55 one-candle daily RSI jump was missed by the hourly-only tiers.
DAILY_RSI_JUMP_THRESHOLD = 15.0

# Wave-independent momentum screen: flagged when >= this many of {1D,4H,1H}
# agree on bullish or bearish momentum (RSI threshold + MACD), independent
# of the wave-composite `direction`. 2-of-3 favors 1D+4H (trend/swing
# context) over pure 1H noise, per this session's 1D=trend/4H=swing/1H=timing
# framework. Added after MORPHOUSD showed RSI 75-76 on 4H/1H (rising, bullish
# MACD) while the 1H composite `direction` was mislabeled "short" by a broken
# wave count -- tiers require direction=="long" so that strength was
# completely invisible regardless of score.
MOMENTUM_SCREEN_MIN_TIMEFRAMES = 2


@dataclass
class BasketRow:
    pair: str
    price: float
    score: float
    direction: str
    rsi: float
    rsi_rising: bool
    macd_bull: bool
    obv_rising: bool
    tier: str  # "", "priority", "approaching", "signal"
    low_wave_confidence: bool = False
    display_label: str = ""
    daily_rsi_jump: float | None = None  # points risen vs prior daily bar, if > threshold
    momentum_screen_hit: str = ""       # "", "bullish", "bearish" -- independent of wave `direction`
    momentum_screen_detail: str = ""    # e.g. "4H:bullish(RSI 75↑) 1H:bullish(RSI 76↑) 1D:neutral(RSI 51↓)"


@dataclass
class BreadthSummary:
    total: int
    rsi_rising: int
    rsi_above_40: int
    macd_bullish: int

    def __str__(self) -> str:
        return (
            f"{self.rsi_rising}/{self.total} RSI rising | "
            f"{self.rsi_above_40}/{self.total} RSI>=40 | "
            f"{self.macd_bullish}/{self.total} MACD bullish"
        )


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


def _momentum_screen(
    df_d: pd.DataFrame | None,
    df_4h: pd.DataFrame | None,
    df_1h: pd.DataFrame,
) -> tuple[str, str]:
    """Wave-independent momentum read across 1D/4H/1H -- never touches
    compute_score()/ScoreBreakdown.direction. Returns ("bullish"/"bearish"/"",
    detail_string). See MOMENTUM_SCREEN_MIN_TIMEFRAMES docstring for why."""
    reads: dict[str, tuple[str, float, bool]] = {}
    for label, tf_df in (("1D", df_d), ("4H", df_4h), ("1H", df_1h)):
        if tf_df is None or len(tf_df) < 2:
            continue
        dm = add_momentum(tf_df.copy())
        direction, _ = momentum_direction(dm)
        rsi_val = float(dm["rsi"].iloc[-1])
        rising = rsi_val > float(dm["rsi"].iloc[-2])
        reads[label] = (direction, rsi_val, rising)

    bull = sum(1 for d, _, up in reads.values() if d == "bullish" and up)
    bear = sum(1 for d, _, up in reads.values() if d == "bearish" and not up)
    detail = " ".join(f"{tf}:{d}(RSI {r:.0f}{'↑' if up else '↓'})" for tf, (d, r, up) in reads.items())

    if bull >= MOMENTUM_SCREEN_MIN_TIMEFRAMES:
        return "bullish", detail
    if bear >= MOMENTUM_SCREEN_MIN_TIMEFRAMES:
        return "bearish", detail
    return "", detail


def scan_basket(
    con,
    config: AppConfig,
    pairs: list[str] | None = None,
    fetch: bool = True,
    check_daily_jump: bool = True,
) -> tuple[list[BasketRow], BreadthSummary]:
    """Score every pair in `pairs` (default DEFAULT_BASKET) on hourly data,
    plus a basket-wide breadth summary (RSI rising / RSI>=40 / MACD bullish
    counts). Breadth matters more than any single pair's score -- isolated
    fires have repeatedly faded all session; the one entry that held (ADAUSD)
    was backed by 24/27 RSI rising, 26/27 RSI>=40, 25/27 MACD bullish.

    If `fetch` is True, pulls fresh candles from Kraken first; set False to
    score whatever is already in the local DuckDB store (faster, offline).
    If `check_daily_jump` is True, also fetches daily candles for every pair
    to flag a >DAILY_RSI_JUMP_THRESHOLD point daily RSI jump regardless of
    hourly score (added after ARBUSD's 39->55 jump was missed on hourly alone)."""
    pairs = pairs or DEFAULT_BASKET
    rows: list[BasketRow] = []

    for pair in pairs:
        if fetch:
            try:
                candles, _ = kraken_rest.get_ohlc(pair, interval=60)
                ohlcv_store.upsert_ohlcv(con, pair, 60, candles)
                if check_daily_jump:
                    daily_candles, _ = kraken_rest.get_ohlc(pair, interval=1440)
                    ohlcv_store.upsert_ohlcv(con, pair, 1440, daily_candles)
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
        rsi_prev = float(dm["rsi"].iloc[-2])
        macd_bull = bool(dm["macd"].iloc[-1] > dm["macd_signal"].iloc[-1])
        obv_rising = bool(dv["obv"].iloc[-1] > dv["obv"].iloc[-6])

        daily_jump = None
        df_d = None
        if check_daily_jump:
            df_d = ohlcv_store.read_ohlcv(con, pair, 1440)
            if len(df_d) >= 2:
                dm_d = add_momentum(df_d.copy())
                jump = float(dm_d["rsi"].iloc[-1] - dm_d["rsi"].iloc[-2])
                if jump > DAILY_RSI_JUMP_THRESHOLD:
                    daily_jump = jump

        # Momentum screen needs 1D context per this project's timeframe
        # philosophy -- skip (leave "") rather than screen off 1H alone when
        # daily data wasn't fetched this run.
        momentum_hit, momentum_detail = "", ""
        if check_daily_jump and df_d is not None and len(df_d) >= 2:
            momentum_hit, momentum_detail = _momentum_screen(df_d, _resample_4h(df), df)

        rows.append(
            BasketRow(
                pair=pair,
                price=price,
                score=bd.total,
                direction=bd.direction,
                rsi=rsi,
                rsi_rising=rsi > rsi_prev,
                macd_bull=macd_bull,
                obv_rising=obv_rising,
                tier=_tier_for(pair, bd.total, bd.direction),
                low_wave_confidence=pair in LOW_WAVE_CONFIDENCE and bool(bd.metadata.get("wave_rule_violations")),
                display_label=DISPLAY_LABEL.get(pair, pair.replace("USD", "")),
                daily_rsi_jump=daily_jump,
                momentum_screen_hit=momentum_hit,
                momentum_screen_detail=momentum_detail,
            )
        )

    rows.sort(key=lambda r: -r.score)

    breadth = BreadthSummary(
        total=len(rows),
        rsi_rising=sum(1 for r in rows if r.rsi_rising),
        rsi_above_40=sum(1 for r in rows if r.rsi >= 40),
        macd_bullish=sum(1 for r in rows if r.macd_bull),
    )
    return rows, breadth


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
