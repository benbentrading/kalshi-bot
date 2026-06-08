# scripts/db_wrapper/db_setup.py
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "activity.sqlite3")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with get_conn() as conn:
        conn.executescript("""

            CREATE TABLE IF NOT EXISTS trades (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms                   INTEGER,
                trade_id                TEXT UNIQUE,
                order_id                TEXT,
                kalshi_event_ticker     TEXT,
                kalshi_market_ticker    TEXT,
                purchased_side          TEXT,
                yes_price_dollars       REAL,
                count_fp                REAL,
                post_position_fp        REAL,
                fee_cost                REAL,
                is_taker                INTEGER,
                vegas_yes_bid           REAL,
                vegas_no_bid            REAL,
                trade_px                REAL,
                ev_dollars              REAL
            );

            CREATE TABLE IF NOT EXISTS market_positions (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms                   INTEGER,
                kalshi_market_ticker    TEXT,
                position_fp             REAL,
                realized_pnl_dollars    REAL,
                fees_paid_dollars       REAL,
                cost_basis_dollars      REAL,
                volume_fp               REAL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms                   INTEGER,
                action                  TEXT,
                kalshi_order_id         TEXT,
                kalshi_market_ticker    TEXT,
                side                    TEXT,
                px                      REAL,
                ctx                     REAL,
                status                  TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms                   INTEGER,
                action                  TEXT,
                kalshi_event_ticker     TEXT,
                boltodds_id             TEXT,
                market_type             TEXT,
                league                  TEXT
            );

        """)

    print(f"db initialized at {DB_PATH}")


if __name__ == "__main__":
    init_db()