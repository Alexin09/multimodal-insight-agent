"""
Database connection layer for Polymarket PostgreSQL.
Provides async-compatible sync connection pool with safety controls.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Load from backend/.env (parent of mcp/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

# ── Config ────────────────────────────────────────────────────
DB_URL = "postgresql://{user}:{pw}@{host}:{port}/{db}".format(
    user=os.getenv("DB_USER"),
    pw=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT", "5432"),
    db=os.getenv("DB_NAME"),
)
DEFAULT_SCHEMA = os.getenv("DB_SCHEMA", "polymarket")
QUERY_TIMEOUT = int(os.getenv("QUERY_TIMEOUT", "60"))
MAX_ROWS = int(os.getenv("MAX_ROWS", "500"))

# ── Dangerous SQL patterns (reject anything that mutates) ─────
_DANGEROUS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)

# ── Engine singleton ──────────────────────────────────────────
_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            DB_URL,
            pool_size=3,
            max_overflow=2,
            pool_timeout=10,
            pool_recycle=300,
            connect_args={"options": f"-c statement_timeout={QUERY_TIMEOUT * 1000}"},
        )
    return _engine


def validate_sql(sql: str) -> str | None:
    """Return error message if SQL is unsafe, else None."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return "Empty SQL"
    if _DANGEROUS_RE.search(stripped):
        return "Only SELECT queries are allowed. Detected mutating statement."
    return None


def execute_query(sql: str, limit: int | None = None) -> dict:
    """
    Execute a read-only SQL query and return results as a dict.

    Returns:
        {
            "columns": [...],
            "rows": [[...], ...],
            "row_count": int,
            "truncated": bool,
        }
    """
    error = validate_sql(sql)
    if error:
        return {"error": error}

    effective_limit = min(limit or MAX_ROWS, MAX_ROWS)

    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys()) if hasattr(result, "keys") else []
            all_rows = result.fetchmany(effective_limit + 1)

            truncated = len(all_rows) > effective_limit
            rows = all_rows[:effective_limit]

            # Convert to JSON-serializable lists
            rows_out = []
            for row in rows:
                rows_out.append([_serialize(v) for v in row])

            return {
                "columns": columns,
                "rows": rows_out,
                "row_count": len(rows_out),
                "truncated": truncated,
            }
    except Exception as e:
        return {"error": str(e)}


def _serialize(value):
    """Convert DB values to JSON-safe types."""
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    # datetime, date, Decimal, etc.
    return str(value)
