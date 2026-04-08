"""
MCP Tool definitions for Polymarket database.
3-tool architecture: find_tables / get_table_schema / run_public_sql_query.
"""

from __future__ import annotations

import json
from mcp.db import execute_query, DEFAULT_SCHEMA


# ── Tool 1: find_tables ──────────────────────────────────────


def find_tables(schema: str | None = None, name_filter: str | None = None) -> str:
    """
    List tables in a schema, optionally filtered by name pattern.

    Args:
        schema: Schema name (default: polymarket)
        name_filter: ILIKE pattern to filter table names, e.g. '%trade%'
    """
    schema = schema or DEFAULT_SCHEMA
    where_clauses = [f"table_schema = '{schema}'"]
    if name_filter:
        # Sanitize: only allow alphanumeric, %, _
        safe_filter = "".join(c for c in name_filter if c.isalnum() or c in "%_-")
        where_clauses.append(f"table_name ILIKE '{safe_filter}'")

    sql = f"""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE {" AND ".join(where_clauses)}
        ORDER BY table_name
    """
    result = execute_query(sql, limit=200)
    if "error" in result:
        return f"Error: {result['error']}"

    tables = [{"name": row[0], "type": row[1]} for row in result["rows"]]
    return json.dumps(
        {"schema": schema, "tables": tables, "count": len(tables)},
        ensure_ascii=False,
    )


# ── Tool 2: get_table_schema ────────────────────────────────


def get_table_schema(table_name: str, schema: str | None = None) -> str:
    """
    Show column names, types, and nullable info for a table.

    Args:
        table_name: The table to describe
        schema: Schema name (default: polymarket)
    """
    schema = schema or DEFAULT_SCHEMA
    # Try information_schema first (works for tables and views)
    sql = f"""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = '{schema}'
          AND table_name = '{table_name}'
        ORDER BY ordinal_position
    """
    result = execute_query(sql, limit=100)

    # Fallback for materialized views: information_schema doesn't list them
    if (not result.get("error")) and len(result.get("rows", [])) == 0:
        sql = f"""
            SELECT
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                pg_get_expr(d.adbin, d.adrelid) AS column_default
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = '{schema}'
              AND c.relname = '{table_name}'
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
        """
        result = execute_query(sql, limit=100)

    if "error" in result:
        return f"Error: {result['error']}"

    columns = []
    for row in result["rows"]:
        columns.append(
            {
                "name": row[0],
                "type": row[1],
                "nullable": row[2],
                "default": row[3],
            }
        )

    return json.dumps(
        {
            "schema": schema,
            "table": table_name,
            "columns": columns,
            "count": len(columns),
        },
        ensure_ascii=False,
    )


# ── Tool 3: run_public_sql_query ─────────────────────────────


def run_public_sql_query(sql: str, limit: int | None = None) -> str:
    """
    Execute a read-only SQL query and return results.
    Only SELECT statements are allowed. Max 500 rows returned.

    Args:
        sql: The SELECT SQL query to execute
        limit: Max rows to return (default 100, max 500)
    """
    effective_limit = min(limit or 100, 500)
    result = execute_query(sql, limit=effective_limit)
    if "error" in result:
        return f"Error: {result['error']}"

    return json.dumps(result, ensure_ascii=False, default=str)
