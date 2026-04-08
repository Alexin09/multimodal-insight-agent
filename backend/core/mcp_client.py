"""
MCP Client: wraps the 3 MCP tools as async functions.
Each tool call emits pipeline events so the frontend can show live status.

Tools:
  find_tables         — list tables by schema + name pattern
  get_table_schema    — describe columns of a table
  run_public_sql_query — execute read-only SQL
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load backend .env (contains DB credentials)
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env", override=True)

from core.pipeline_events import emit_start, emit_done

# ── Import built-in MCP tools directly ───

_tools_module = None


def _get_tools():
    """Import MCP tools from the built-in mcp/ package."""
    global _tools_module
    if _tools_module is not None:
        return _tools_module

    from mcp import tools as mcp_tools

    _tools_module = mcp_tools
    return _tools_module


# ── Tool wrappers (async interface, sync under the hood) ──────


async def find_tables(schema: str = "polymarket", name_filter: str = "") -> dict:
    """List tables in a schema."""
    await emit_start("mcp.find_tables", {"schema": schema, "filter": name_filter})
    tools = _get_tools()
    raw = tools.find_tables(schema=schema, name_filter=name_filter or None)
    result = json.loads(raw) if not raw.startswith("Error") else {"error": raw}
    count = len(result.get("tables", [])) if isinstance(result, dict) else 0
    await emit_done("mcp.find_tables", result=f"{count} tables")
    return result


async def get_table_schema(table_name: str, schema: str = "polymarket") -> dict:
    """Describe a table's columns."""
    await emit_start("mcp.get_table_schema", {"table": table_name})
    tools = _get_tools()
    raw = tools.get_table_schema(table_name=table_name, schema=schema)
    result = json.loads(raw) if not raw.startswith("Error") else {"error": raw}
    col_count = len(result.get("columns", [])) if isinstance(result, dict) else 0
    await emit_done("mcp.get_table_schema", result=f"{table_name}: {col_count} cols")
    return result


async def run_public_sql_query(sql: str, limit: int = 100) -> dict:
    """Execute a read-only SQL query."""
    # Truncate SQL for display (keep first 80 chars)
    display_sql = sql[:80] + ("..." if len(sql) > 80 else "")
    await emit_start("mcp.run_public_sql_query", {"sql": display_sql, "limit": limit})
    tools = _get_tools()
    raw = tools.run_public_sql_query(sql=sql, limit=limit)
    result = json.loads(raw) if not raw.startswith("Error") else {"error": raw}
    row_count = len(result.get("rows", [])) if isinstance(result, dict) else 0
    await emit_done("mcp.run_public_sql_query", result=f"{row_count} rows returned")
    return result


# ── Schema discovery for Text2SQL prompt ──────────────────────


# Core tables to describe (skip partitions, history snapshots, internal tables)
_CORE_TABLES = [
    "p_markets",
    "p_events",
    "p_assets",
    "p_clobtokens",
    "p_polymarket_trades_d",  # view across all trade partitions
    "p_polymarket_users",
    "p_polymarket_pnl",
    "p_polymarket_total_pnl_v",
    "p_polymarket_trader_pnl_history",
    "p_polymarket_trader_smart",
    "p_polymarket_rewards",
    "p_polymarket_tags",
    "p_polymarket_tags_relations",
    "p_polymarket_market_price_history",
    "p_polymarket_profile_strategy",
]


async def get_full_schema_description() -> str:
    """
    Get schema for core tables only (fast — ~15 get_table_schema calls instead of 108).
    Returns a formatted string suitable for LLM prompt injection.

    Emits a single high-level "schema_discovery" event that wraps all
    individual get_table_schema calls, so the UI shows one clean line
    instead of 15 separate tool-call indicators.
    """
    try:
        await emit_start("mcp.schema_discovery", {"tables": len(_CORE_TABLES)})
        lines = ["DATABASE SCHEMA (PostgreSQL, schema: polymarket):\n"]
        loaded = 0

        for tname in _CORE_TABLES:
            try:
                # Individual get_table_schema calls still emit their own events
                desc = await get_table_schema(tname, schema="polymarket")
                columns = desc.get("columns", [])
                if not columns:
                    continue

                loaded += 1
                lines.append(f"TABLE: polymarket.{tname}")
                for col in columns:
                    nullable = "NULL" if col.get("nullable") == "YES" else "NOT NULL"
                    lines.append(f"  - {col['name']:30s} {col['type']:20s} {nullable}")
                lines.append("")
            except Exception:
                # Table might not exist, skip
                continue

        lines.append(
            "NOTE: Trades are partitioned by month in tables poly_trades_d_YYYYMM."
        )
        lines.append("Use the view p_polymarket_trades_d for cross-month queries.")
        lines.append(
            "Use find_tables / get_table_schema for other tables not listed above.\n"
        )

        await emit_done("mcp.schema_discovery", result=f"{loaded} tables loaded")
        return "\n".join(lines)

    except Exception as e:
        await emit_done("mcp.schema_discovery", result=f"failed: {e}")
        return f"[Schema discovery failed: {e}]"
