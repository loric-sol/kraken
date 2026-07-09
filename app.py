"""Streamlit dashboard for the kraken_ew Elliott Wave + quant confirmation
system: run the basket scanner, review open positions (paper ledger + SOL
multi-timeframe read), and track assessed trades with entry/stop/TP levels.

Usage:
    streamlit run app.py

All scanning is manual (a "Run Scan" button) -- no background polling, so it
never hammers Kraken's API just from having the tab open.
"""

from __future__ import annotations

import warnings

import pandas as pd
import streamlit as st

warnings.filterwarnings("ignore")

from kraken_ew.config import load_config
from kraken_ew.dashboard.scan import (
    DEFAULT_BASKET,
    TIER_APPROACHING,
    TIER_PRIORITY,
    TIER_SIGNAL,
    multi_timeframe,
    scan_basket,
)
from kraken_ew.data import ohlcv_store, trades_store
from kraken_ew.live import kraken_paper_cli

st.set_page_config(page_title="Kraken EW Dashboard", layout="wide")

TIER_LABELS = {"signal": "🚨 SIGNAL (>=70)", "approaching": "👀 APPROACHING (>=65)", "priority": "⭐ PRIORITY (>=60)", "": ""}


@st.cache_resource
def get_config():
    return load_config()


config = get_config()

st.title("Kraken EW — Elliott Wave + Quant Confirmation Dashboard")
st.caption(
    "⚠️ Per docs/falsification_plan.md, this composite has no proven edge "
    "(flat-to-negative out-of-sample in bull AND bear walk-forward tests). "
    "Signals here are review triggers, not high-confidence trades."
)

tab_scanner, tab_positions, tab_trades = st.tabs(["📡 Scanner", "📊 Open Positions", "📒 Trade Log"])

# ---------------------------------------------------------------- Scanner --
with tab_scanner:
    col1, col2 = st.columns([1, 3])
    with col1:
        run_clicked = st.button("🔄 Run Scan", type="primary", width="stretch")
        use_cache = st.checkbox("Use cached data (skip Kraken fetch)", value=False)
    with col2:
        st.write(
            f"Basket: {len(DEFAULT_BASKET)} pairs · "
            f"Tiers: ⭐{TIER_PRIORITY:.0f} (priority watch) · 👀{TIER_APPROACHING:.0f} · 🚨{TIER_SIGNAL:.0f}"
        )

    if run_clicked:
        with st.spinner("Fetching + scoring basket..."):
            with ohlcv_store.connect() as con:
                rows, breadth = scan_basket(con, config, fetch=not use_cache)
        st.session_state["scan_rows"] = rows
        st.session_state["scan_breadth"] = breadth
        st.session_state["scan_time"] = pd.Timestamp.utcnow()

    rows = st.session_state.get("scan_rows")
    if rows is None:
        st.info("Click **Run Scan** to fetch live data and score the basket.")
    else:
        st.caption(f"Last scanned: {st.session_state['scan_time']:%Y-%m-%d %H:%M UTC}")

        breadth = st.session_state.get("scan_breadth")
        if breadth:
            st.info(
                f"**Breadth:** {breadth}  \n"
                "A single pair firing while the rest of the basket has falling RSI has "
                "repeatedly faded this session — the entry that held (ADAUSD) had strong "
                "breadth (24/27 rising, 26/27 ≥40, 25/27 bullish MACD) behind it."
            )

        jumps = [r for r in rows if r.daily_rsi_jump]
        if jumps:
            st.warning(
                "📈 **Daily RSI jump** (>15pt vs prior daily bar, may not show on hourly score): "
                + ", ".join(f"{r.display_label} (+{r.daily_rsi_jump:.0f}pt)" for r in jumps)
            )

        df = pd.DataFrame(
            [
                {
                    "Pair": r.display_label,
                    "Price": r.price,
                    "Score": round(r.score, 1),
                    "Direction": r.direction,
                    "RSI": round(r.rsi, 0),
                    "RSI dir": "↑" if r.rsi_rising else "↓",
                    "MACD": "bull" if r.macd_bull else "bear",
                    "OBV": "↑" if r.obv_rising else "↓",
                    "Tier": TIER_LABELS[r.tier] + (" ⚠️ low wave-conf" if r.low_wave_confidence else ""),
                }
                for r in rows
            ]
        )

        fired = df[df["Tier"] != ""]
        if not fired.empty:
            st.subheader("Fired tiers")
            st.dataframe(fired, width="stretch", hide_index=True)
        else:
            st.caption("No pair crossed a watch/signal tier this scan.")

        st.subheader("Full basket (sorted by score)")
        st.dataframe(df, width="stretch", hide_index=True)

        st.divider()
        st.subheader("Multi-timeframe assessment")
        pair_choice = st.selectbox("Pair", [r.pair for r in rows], key="mtf_pair")
        if st.button("Assess (1D / 4H / 1H)"):
            with st.spinner(f"Pulling daily + 4H + hourly for {pair_choice}..."):
                with ohlcv_store.connect() as con:
                    mtf = multi_timeframe(con, config, pair_choice, fetch=not use_cache)
            st.session_state["mtf_result"] = mtf

        mtf = st.session_state.get("mtf_result")
        if mtf and mtf.pair == pair_choice:
            st.metric(f"{mtf.pair} price", f"${mtf.price:,.4f}")
            c1, c2, c3 = st.columns(3)
            for col, tf in zip((c1, c2, c3), (mtf.daily, mtf.four_hour, mtf.hourly)):
                with col:
                    st.markdown(f"**{tf.timeframe}**")
                    st.write(f"Score: {tf.score:.1f} ({tf.direction})")
                    arrow = "↑" if tf.rsi > tf.rsi_prev else "↓"
                    st.write(f"RSI: {tf.rsi:.1f} {arrow}")
                    st.write(f"MACD: {'bull' if tf.macd_bull else 'bear'}")
                    st.write(f"ATR: {tf.atr_value:.4f}")

            if mtf.trade_plan:
                tp = mtf.trade_plan
                st.markdown(f"**Trade plan ({tp.direction})** — stop on hourly ATR, targets on daily ATR")
                plan_df = pd.DataFrame(
                    {
                        "Level": ["Entry", "Stop", "TP1", "TP2", "TP3"],
                        "Price": [tp.entry, tp.stop, tp.tp1, tp.tp2, tp.tp3],
                    }
                )
                st.dataframe(plan_df, width="stretch", hide_index=True)
                st.caption(f"Position ≈ ${tp.position_value:,.0f}, risking ≈ ${tp.risk_usd:.0f}")

                with st.form("log_trade_form"):
                    st.write("Log this as a tracked trade:")
                    notes = st.text_input("Notes", value=f"score-driven entry, {pair_choice}")
                    submitted = st.form_submit_button("➕ Add to Trade Log")
                    if submitted:
                        with trades_store.connect() as con:
                            trades_store.open_trade(
                                con, pair_choice, tp.direction, entry_price=tp.entry,
                                stop_price=tp.stop, tp1_price=tp.tp1, tp2_price=tp.tp2, tp3_price=tp.tp3,
                                volume=tp.position_value / tp.entry if tp.entry else None,
                                score=mtf.hourly.score, notes=notes,
                            )
                        st.success(f"Logged {pair_choice} {tp.direction} trade.")

# --------------------------------------------------------- Open Positions --
with tab_positions:
    st.subheader("Paper account (Kraken CLI ledger)")
    try:
        status = kraken_paper_cli.paper_status()
        c1, c2, c3 = st.columns(3)
        c1.metric("Account value", f"${status['current_value']:,.2f}")
        c2.metric("Unrealized P&L", f"${status.get('unrealized_pnl', 0):,.2f}",
                   f"{status.get('unrealized_pnl_pct', 0):+.3f}%")
        c3.metric("Total trades", status.get("total_trades", 0))
    except Exception as e:
        st.warning(f"Could not reach `kraken paper status`: {e}")

    st.divider()
    st.subheader("Open tracked trades")
    with trades_store.connect() as con:
        open_trades = trades_store.list_trades(con, status="open")
    if open_trades.empty:
        st.caption("No open trades in the log.")
    else:
        for _, row in open_trades.iterrows():
            with st.container(border=True):
                cols = st.columns([2, 1, 1, 1, 1, 1])
                cols[0].markdown(f"**{row['pair']}** ({row['direction']})")
                cols[1].write(f"Entry ${row['entry_price']:.4f}")
                cols[2].write(f"Stop ${row['stop_price']:.4f}" if pd.notna(row["stop_price"]) else "Stop —")
                cols[3].write(f"TP1 ${row['tp1_price']:.4f}" if pd.notna(row["tp1_price"]) else "TP1 —")
                cols[4].write(f"TP2 ${row['tp2_price']:.4f}" if pd.notna(row["tp2_price"]) else "TP2 —")

                if cols[5].button("Assess now", key=f"assess_{row['trade_id']}"):
                    with st.spinner(f"Pulling 1D/4H/1H for {row['pair']}..."):
                        with ohlcv_store.connect() as con:
                            mtf = multi_timeframe(con, config, row["pair"])
                    sign = 1 if row["direction"] == "long" else -1
                    pnl = sign * (mtf.price / row["entry_price"] - 1) * 100
                    st.metric(f"{row['pair']} now", f"${mtf.price:,.4f}", f"{pnl:+.2f}% vs entry")
                    d1, d2, d3 = st.columns(3)
                    for col, tf in zip((d1, d2, d3), (mtf.daily, mtf.four_hour, mtf.hourly)):
                        col.write(f"**{tf.timeframe}**: {tf.direction} score {tf.score:.0f}, RSI {tf.rsi:.0f}, "
                                  f"MACD {'bull' if tf.macd_bull else 'bear'}")

                with st.expander("Close this trade"):
                    exit_price = st.number_input(
                        "Exit price", min_value=0.0, format="%.5f", key=f"exit_{row['trade_id']}"
                    )
                    close_notes = st.text_input("Close notes", key=f"notes_{row['trade_id']}")
                    if st.button("Close trade", key=f"close_{row['trade_id']}"):
                        if exit_price > 0:
                            with trades_store.connect() as con:
                                trades_store.close_trade(con, row["trade_id"], exit_price, notes=close_notes)
                            st.success(f"Closed {row['pair']} at ${exit_price:.5f}. Refresh to update.")
                        else:
                            st.error("Enter a nonzero exit price.")

# --------------------------------------------------------------- Trade Log --
with tab_trades:
    st.subheader("All tracked trades")
    with trades_store.connect() as con:
        all_trades = trades_store.list_trades(con)
    if all_trades.empty:
        st.caption("No trades logged yet.")
    else:
        display_cols = [
            "trade_id", "pair", "direction", "status", "entry_price", "stop_price",
            "tp1_price", "tp2_price", "tp3_price", "exit_price", "pnl_pct",
            "opened_at", "closed_at", "notes",
        ]
        st.dataframe(all_trades[display_cols], width="stretch", hide_index=True)

        closed = all_trades[all_trades["status"] == "closed"]
        if not closed.empty:
            st.divider()
            st.subheader("Closed-trade summary")
            c1, c2, c3 = st.columns(3)
            c1.metric("Closed trades", len(closed))
            c2.metric("Win rate", f"{(closed['pnl_pct'] > 0).mean() * 100:.0f}%")
            c3.metric("Avg P&L", f"{closed['pnl_pct'].mean():+.2f}%")
