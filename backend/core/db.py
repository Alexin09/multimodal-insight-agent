"""
Database abstraction layer.

Two modes controlled by DB_MODE env var:
  - "sqlite" (default): local SQLite with sample data for demo/testing
  - "mcp": connects to polydata-db-mcp for real PostgreSQL data

The rest of the app calls get_schema_description() and run_query()
without caring which backend is active.
"""

import os
import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_MODE = os.getenv("DB_MODE", "sqlite")  # "sqlite" or "mcp"
DB_PATH = Path(__file__).parent.parent / "data" / "sample.db"

# Note: Schema discovery is now handled dynamically by the Agent in text2sql.py
# via MCP tool calls (find_tables → get_table_schema). No more static cache.


# ══════════════════════════════════════════════════════════════
#  Public API — used by text2sql.py and server.py
# ══════════════════════════════════════════════════════════════


async def get_schema_description() -> str:
    """Return schema description string for LLM prompt."""
    if DB_MODE == "mcp":
        return await _get_mcp_schema()
    return _get_sqlite_schema()


async def run_query(sql: str) -> list[dict]:
    """Execute a read-only query. Returns list of row dicts."""
    if DB_MODE == "mcp":
        return await _run_mcp_query(sql)
    return _run_sqlite_query(sql)


# ══════════════════════════════════════════════════════════════
#  MCP backend
# ══════════════════════════════════════════════════════════════


async def _get_mcp_schema() -> str:
    """Return a minimal schema hint. Full discovery is done by the Agent."""
    return (
        "DATABASE: PostgreSQL (schema: polymarket)\n"
        "Use the Agent's MCP tools (find_tables, get_table_schema) to discover tables and columns.\n"
        "Trade data is partitioned by month in tables poly_trades_d_YYYYMM.\n"
        "Use the view p_polymarket_trades_d for cross-month trade queries.\n"
    )


async def _run_mcp_query(sql: str) -> list[dict]:
    from core.mcp_client import run_public_sql_query

    result = await run_public_sql_query(sql, limit=100)

    if "error" in result:
        raise RuntimeError(result["error"])

    columns = result.get("columns", [])
    rows = result.get("rows", [])
    return [dict(zip(columns, row)) for row in rows]


# ══════════════════════════════════════════════════════════════
#  SQLite backend (demo / mock)
# ══════════════════════════════════════════════════════════════


def get_connection() -> sqlite3.Connection:
    """Return a sqlite3 connection. Creates DB + tables if missing."""
    first_run = not DB_PATH.exists()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if first_run:
        _init_schema(conn)
        _seed_data(conn)
    return conn


def _get_sqlite_schema() -> str:
    return """
DATABASE SCHEMA (SQLite):

TABLE: markets
  - id            INTEGER PRIMARY KEY
  - title         TEXT        -- market/event title
  - category      TEXT        -- e.g. 'politics','sports','crypto','entertainment'
  - status        TEXT        -- 'active','resolved'
  - created_at    TEXT        -- ISO timestamp
  - resolved_at   TEXT        -- ISO timestamp or NULL
  - outcome       TEXT        -- 'yes','no', or NULL if unresolved
  - total_volume  REAL        -- total trading volume in USD

TABLE: trades
  - id            INTEGER PRIMARY KEY
  - market_id     INTEGER     -- FK → markets.id
  - trader_addr   TEXT        -- anonymized trader identifier
  - side          TEXT        -- 'yes' or 'no'
  - amount        REAL        -- trade size in USD
  - price         REAL        -- execution price (0.00–1.00)
  - timestamp     TEXT        -- ISO timestamp

TABLE: daily_snapshots
  - id            INTEGER PRIMARY KEY
  - market_id     INTEGER     -- FK → markets.id
  - date          TEXT        -- YYYY-MM-DD
  - yes_price     REAL        -- closing yes-side price
  - no_price      REAL        -- closing no-side price
  - volume        REAL        -- daily volume in USD
  - num_traders   INTEGER     -- unique traders that day

TABLE: traders
  - addr          TEXT PRIMARY KEY -- anonymized trader identifier
  - total_pnl     REAL        -- realized profit/loss in USD
  - win_rate      REAL        -- 0.00–1.00
  - num_trades    INTEGER
  - first_seen    TEXT        -- ISO timestamp
  - last_seen     TEXT        -- ISO timestamp
"""


def _run_sqlite_query(sql: str) -> list[dict]:
    conn = get_connection()
    try:
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


# ── SQLite schema init & seed ─────────────────────────────────


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS markets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            category      TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'active',
            created_at    TEXT NOT NULL,
            resolved_at   TEXT,
            outcome       TEXT,
            total_volume  REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id     INTEGER NOT NULL,
            trader_addr   TEXT NOT NULL,
            side          TEXT NOT NULL,
            amount        REAL NOT NULL,
            price         REAL NOT NULL,
            timestamp     TEXT NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id)
        );
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id     INTEGER NOT NULL,
            date          TEXT NOT NULL,
            yes_price     REAL NOT NULL,
            no_price      REAL NOT NULL,
            volume        REAL NOT NULL,
            num_traders   INTEGER NOT NULL,
            FOREIGN KEY (market_id) REFERENCES markets(id)
        );
        CREATE TABLE IF NOT EXISTS traders (
            addr          TEXT PRIMARY KEY,
            total_pnl     REAL NOT NULL DEFAULT 0,
            win_rate      REAL NOT NULL DEFAULT 0,
            num_trades    INTEGER NOT NULL DEFAULT 0,
            first_seen    TEXT NOT NULL,
            last_seen     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id);
        CREATE INDEX IF NOT EXISTS idx_trades_trader ON trades(trader_addr);
        CREATE INDEX IF NOT EXISTS idx_snapshots_market_date ON daily_snapshots(market_id, date);
    """)
    conn.commit()


def _seed_data(conn: sqlite3.Connection):
    random.seed(42)
    now = datetime(2025, 4, 1)

    market_templates = [
        ("US Presidential Election 2028 Winner", "politics"),
        ("Bitcoin above $150k by Dec 2025", "crypto"),
        ("NBA Finals 2025 Champion", "sports"),
        ("Fed Rate Cut in June 2025", "economics"),
        ("Oscar Best Picture 2026", "entertainment"),
        ("Ethereum ETF Approval Q3 2025", "crypto"),
        ("UFC 310 Main Event Winner", "sports"),
        ("US GDP Growth > 3% Q2 2025", "economics"),
        ("Next Twitter CEO Announcement", "tech"),
        ("Champions League 2025 Winner", "sports"),
        ("AI Model Passes Bar Exam 2025", "tech"),
        ("Gold Price Above $3500 by July 2025", "economics"),
    ]

    market_ids = []
    for i, (title, cat) in enumerate(market_templates):
        created = now - timedelta(days=random.randint(30, 180))
        is_resolved = random.random() < 0.3
        resolved_at = (
            (created + timedelta(days=random.randint(15, 90))).isoformat()
            if is_resolved
            else None
        )
        outcome = random.choice(["yes", "no"]) if is_resolved else None
        vol = round(random.uniform(50_000, 5_000_000), 2)
        conn.execute(
            "INSERT INTO markets (title,category,status,created_at,resolved_at,outcome,total_volume) VALUES (?,?,?,?,?,?,?)",
            (
                title,
                cat,
                "resolved" if is_resolved else "active",
                created.isoformat(),
                resolved_at,
                outcome,
                vol,
            ),
        )
        market_ids.append(i + 1)

    trader_addrs = [f"0x{random.randbytes(6).hex()}" for _ in range(80)]
    for addr in trader_addrs:
        first = now - timedelta(days=random.randint(60, 365))
        last = now - timedelta(days=random.randint(0, 30))
        conn.execute(
            "INSERT INTO traders (addr,total_pnl,win_rate,num_trades,first_seen,last_seen) VALUES (?,?,?,?,?,?)",
            (
                addr,
                round(random.uniform(-10000, 50000), 2),
                round(random.uniform(0.25, 0.85), 3),
                random.randint(5, 500),
                first.isoformat(),
                last.isoformat(),
            ),
        )

    for _ in range(2000):
        mid = random.choice(market_ids)
        addr = random.choice(trader_addrs)
        ts = now - timedelta(hours=random.randint(1, 4000))
        conn.execute(
            "INSERT INTO trades (market_id,trader_addr,side,amount,price,timestamp) VALUES (?,?,?,?,?,?)",
            (
                mid,
                addr,
                random.choice(["yes", "no"]),
                round(random.uniform(10, 10000), 2),
                round(random.uniform(0.05, 0.95), 3),
                ts.isoformat(),
            ),
        )

    for mid in market_ids:
        base_price = random.uniform(0.2, 0.8)
        for day_offset in range(90):
            d = (now - timedelta(days=90) + timedelta(days=day_offset)).strftime(
                "%Y-%m-%d"
            )
            drift = random.gauss(0, 0.02)
            base_price = max(0.05, min(0.95, base_price + drift))
            conn.execute(
                "INSERT INTO daily_snapshots (market_id,date,yes_price,no_price,volume,num_traders) VALUES (?,?,?,?,?,?)",
                (
                    mid,
                    d,
                    round(base_price, 4),
                    round(1 - base_price, 4),
                    round(random.uniform(500, 80000), 2),
                    random.randint(5, 200),
                ),
            )

    conn.commit()
