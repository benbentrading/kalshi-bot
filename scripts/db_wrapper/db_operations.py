# scripts/db_wrapper/db_operations.py
import sqlite3
import time
from scripts.db_wrapper.db_setup import get_conn


#################
#    TRADES     #
#################

def insert_trade(
    msg: dict,
    kalshi_event_ticker: str,
    vegas_yes_bid: float,
    vegas_no_bid: float,
    trade_px: float,
    ev_dollars: float
) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO trades
            (ts_ms, trade_id, order_id, kalshi_event_ticker, kalshi_market_ticker,
             purchased_side, yes_price_dollars, count_fp, post_position_fp,
             fee_cost, is_taker, vegas_yes_bid, vegas_no_bid, trade_px, ev_dollars)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg.get("ts_ms"),
            msg.get("trade_id"),
            msg.get("order_id"),
            kalshi_event_ticker,
            msg.get("market_ticker"),
            msg.get("purchased_side"),
            float(msg.get("yes_price_dollars", 0)),
            float(msg.get("count_fp", 0)),
            float(msg.get("post_position_fp", 0)),
            float(msg.get("fee_cost", 0)),
            int(msg.get("is_taker", 0)),
            vegas_yes_bid,
            vegas_no_bid,
            trade_px,
            ev_dollars,
        ))


def get_trades(market_ticker: str = None, kalshi_event_ticker: str = None) -> list:
    with get_conn() as conn:
        if market_ticker:
            rows = conn.execute(
                "SELECT * FROM trades WHERE kalshi_market_ticker = ? ORDER BY ts_ms DESC",
                (market_ticker,)
            ).fetchall()
        elif kalshi_event_ticker:
            rows = conn.execute(
                "SELECT * FROM trades WHERE kalshi_event_ticker = ? ORDER BY ts_ms DESC",
                (kalshi_event_ticker,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY ts_ms DESC"
            ).fetchall()
        return [dict(r) for r in rows]


######################
#  MARKET POSITIONS  #
######################

def insert_market_position(msg: dict) -> None:
    vlm_key = "volume_fp" if "volume_fp" in msg else "total_traded_dollars"
    cost_key = "position_cost_dollars" if "position_cost_dollars" in msg else "market_exposure_dollars"

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO market_positions
            (ts_ms, kalshi_market_ticker, position_fp, realized_pnl_dollars,
             fees_paid_dollars, cost_basis_dollars, volume_fp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            int(time.time() * 1000),
            msg.get("market_ticker") or msg.get("ticker"),
            float(msg.get("position_fp", 0)),
            float(msg.get("realized_pnl_dollars", 0)),
            float(msg.get("fees_paid_dollars", 0)),
            float(msg.get(cost_key, 0)),
            float(msg.get(vlm_key, 0)),
        ))


def get_market_positions(market_ticker: str = None) -> list:
    with get_conn() as conn:
        if market_ticker:
            rows = conn.execute(
                "SELECT * FROM market_positions WHERE kalshi_market_ticker = ? ORDER BY ts_ms DESC",
                (market_ticker,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM market_positions ORDER BY ts_ms DESC"
            ).fetchall()
        return [dict(r) for r in rows]


#############
#  ORDERS   #
#############

def insert_order(
    action: str,
    kalshi_order_id: str,
    kalshi_market_ticker: str,
    side: str,
    px: float,
    ctx: float,
    status: str,
) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO orders
            (ts_ms, action, kalshi_order_id, kalshi_market_ticker,
             side, px, ctx, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(time.time() * 1000),   # ts_ms
            action,
            kalshi_order_id,
            kalshi_market_ticker,
            side,
            px,
            ctx,
            status,
        ))


def get_orders(market_ticker: str = None, kalshi_event_ticker: str = None) -> list:
    with get_conn() as conn:
        if market_ticker:
            rows = conn.execute(
                "SELECT * FROM orders WHERE kalshi_market_ticker = ? ORDER BY ts_ms DESC",
                (market_ticker,)
            ).fetchall()
        elif kalshi_event_ticker:
            rows = conn.execute(
                "SELECT * FROM orders WHERE kalshi_event_ticker = ? ORDER BY ts_ms DESC",
                (kalshi_event_ticker,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY ts_ms DESC"
            ).fetchall()
        return [dict(r) for r in rows]


#############
#  EVENTS   #
#############

def insert_event(
    action: str,
    kalshi_event_ticker: str,
    boltodds_id: str,
    market_type: str,
    league: str
) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO events
            (ts_ms, action, kalshi_event_ticker, boltodds_id, market_type, league)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            int(time.time() * 1000),
            action,
            kalshi_event_ticker,
            boltodds_id,
            market_type,
            league,
        ))


def get_events() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY ts_ms DESC"
        ).fetchall()
        return [dict(r) for r in rows]