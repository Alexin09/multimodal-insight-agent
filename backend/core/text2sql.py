"""
Text2SQL Agent: LLM-driven dynamic schema discovery + SQL generation.

Flow:
  1. LLM analyzes the question → decides which MCP tools to call
  2. Agent loop: LLM calls find_tables / get_table_schema as needed
  3. Once LLM has enough context, it generates SQL
  4. Execute SQL via run_public_sql_query → return results

Each step emits pipeline events for the frontend tool-call status display.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from core.llm_client import chat
from core.pipeline_events import emit_start, emit_done
from core import mcp_client

# ── Agent system prompt ───────────────────────────────────────

AGENT_SYSTEM = """You are a data analysis agent (HermoResearch.ai) with access to a PostgreSQL database (Polymarket prediction market data).

CURRENT TIME: $CURRENT_TIME$

You have these tools to discover the database schema and execute queries:

1. find_tables(schema, name_filter) — List tables in a schema. Use name_filter for ILIKE pattern (e.g. '%trade%').
2. get_table_schema(table_name, schema) — Get column names, types for a specific table.
3. run_public_sql_query(sql) — Execute a read-only SELECT query.

═══════════════════════════════════════════
CORE TABLE REFERENCE (use these FIRST, only call get_table_schema if you need exact column names):
═══════════════════════════════════════════

Markets & Events:
  p_markets           — Market listings (question, volume, active, market_type, events)
  p_events            — Event metadata (id, tags — JSON array, first element is category)
  p_clobtokens        — Maps market_id → clob_token_ids (the token identifier used in trades/pnl)
  p_assets            — Token assets with outcome labels

Trades:
  p_polymarket_trades_with_price_v  — Trade view with price info. Columns: tx_hash, block_timestamp_utc8 (timestamp, UTC+8), address, token_id, action (BUY/SELL), amount, usd, outcomes, outcome_prices, closed (boolean), question
  p_polymarket_trades_d             — Cross-month trade view (no price). Use trades_with_price_v when price is needed.
  poly_trades_d_YYYYMM              — Monthly partitions (e.g. poly_trades_d_202604). Use for current-month-only queries.
  NOTE: The timestamp column is "block_timestamp_utc8" (NOT "block_timestamp"). It is already in UTC+8.

Users & PNL:
  p_polymarket_users            — User profiles
  p_polymarket_pnl              — Per-token PNL: address, token_id, total_bought_cost, fifo_total_pnl, avg_total_pnl, total_remaining
  p_polymarket_total_pnl_v      — ★ Aggregated PNL view by address+token_id (use this for PNL analysis)
  p_polymarket_trader_info_mv   — ★ Materialized view: total_pnl, median_buy_price, win_rate, avg_daily_trades, active_days, reward_7d, reward_30d, earlist_trade_time
  p_polymarket_trader_smart     — Smart trader rankings: address, win_rate, total_pnl, pnl_7d, pnl_30d, specialty_tag
  p_polymarket_trader_pnl_history_new — Daily PNL snapshots: address, pnl_date, total_pnl

Rewards & Tags:
  p_polymarket_rewards          — On-chain reward transfers: to_address, transfer_amount_usd, block_timestamp
  p_polymarket_tags             — Market tag definitions
  p_polymarket_tags_relations   — Market-to-tag mappings
  p_polymarket_market_price_history — Price history: t, p, outcome

Strategy (dev schema):
  dev.p_polymarket_profile_strategy_user — Links address → profile_strategy_id
  dev.p_polymarket_profile_strategy       — Strategy definitions: id, name
  dev.polymarket_toptrader_tags_new       — tag_summary (JSONB): per-tag score, win_rate, trade_cnt

═══════════════════════════════════════════
CRITICAL JOIN PATTERNS (from production queries):
═══════════════════════════════════════════

1. Market → Token IDs:
   p_clobtokens.market_id = p_markets.id
   Then use p_clobtokens.clob_token_ids to join with trade/pnl tables on token_id.

2. Trade → Market name:
   p_polymarket_trades_with_price_v already has question and label columns — NO need to join.

3. Trade → Event category (tags):
   trades.token_id → p_clobtokens (token_id = clob_token_ids)
   → p_markets (market_id) → p_events (events = id)
   Tags are JSON array: use (tags::json->>1) for the second-level category tag.

4. User PNL + Strategy:
   p_polymarket_total_pnl_v ON address
   LEFT JOIN dev.p_polymarket_profile_strategy_user ON address
   LEFT JOIN dev.p_polymarket_profile_strategy ON profile_strategy_id = id

5. User tag performance (JSONB):
   dev.polymarket_toptrader_tags_new.tag_summary is JSONB.
   Access like: (tag_summary->'NBA'->>'win_rate')::numeric
   Expand all tags: CROSS JOIN LATERAL jsonb_each(tag_summary) AS j(tag_name, tag_data)

═══════════════════════════════════════════
⚠ LARGE TABLE REGISTRY (MUST READ BEFORE WRITING ANY SQL):
═══════════════════════════════════════════

Query timeout is 60 seconds. The following tables are HUGE and WILL timeout without proper filtering.
You MUST pick the right strategy BEFORE writing SQL — never do full-table scans on these.

| Table                               | Est. Rows    | MANDATORY Strategy                                     |
|--------------------------------------|-------------|--------------------------------------------------------|
| p_polymarket_trades_d                | ~430M       | ❌ NEVER query directly. Use monthly partition below.  |
| p_polymarket_trades_with_price_v     | ~430M       | ❌ NEVER aggregate (SUM/COUNT/MAX) without address/token_id filter. For time-range aggregates, use monthly partition. |
| poly_trades_d_YYYYMM                | 30M-330M/mo | ✅ Use the specific month partition. Current month: match $CURRENT_TIME$. |
| p_polymarket_pnl                     | ~150M       | ✅ Always filter by address or token_id.               |
| p_polymarket_trader_pnl_history_new  | ~96M        | ✅ Always filter by address AND/OR pnl_date range.     |
| p_polymarket_market_price_history    | ~15M        | ✅ Always filter by market/outcome + time range.       |
| p_polymarket_profile_strategy_user   | ~12M        | ✅ Filter by address.                                  |

SAFE alternatives (pre-aggregated, can query freely):
| Table                               | Est. Rows | Use for                                                |
|--------------------------------------|----------|--------------------------------------------------------|
| p_polymarket_trader_info_mv          | ~370K    | ★ User stats: total_pnl, win_rate, avg_daily_trades   |
| p_polymarket_trader_smart            | small    | ★ Trader rankings: pnl_7d, pnl_30d, win_rate          |
| p_polymarket_total_pnl_v             | medium   | ★ Aggregated PNL by address+token_id                  |
| p_markets                            | ~670K    | Markets metadata — safe to aggregate                   |
| p_polymarket_rewards                 | ~620K    | Rewards data — safe with time filter                   |

DECISION TREE — follow this BEFORE writing SQL:
1. Question about trader stats/rankings/PNL? → Use p_polymarket_trader_info_mv or p_polymarket_trader_smart. DONE.
2. Question about trade volume/count over a time range?
   a. Range ≤ 1 month → Use the specific poly_trades_d_YYYYMM partition.
   b. Range > 1 month → UNION the relevant monthly partitions (max 3 months), NOT the full view.
3. Question about a specific address or token? → trades_with_price_v is OK (indexed lookup).
4. Question about "latest trade time"? → Use current month partition + ORDER BY DESC LIMIT 1.
5. Question about market info (volume, active, etc.)? → Use p_markets directly.
6. Need approximate total row count? → SELECT reltuples::bigint FROM pg_class WHERE relname = '...'.

═══════════════════════════════════════════
SQL RULES & PITFALLS:
═══════════════════════════════════════════

- Default schema: "polymarket". Always qualify: polymarket.table_name
- For dev schema tables: dev.table_name
- Trade partitions: poly_trades_d_YYYYMM. For current month, use the partition matching CURRENT TIME above.
- Time filters: use NOW(), CURRENT_DATE, INTERVAL '7 days' etc. Never hardcode dates.
- NULLS LAST on ORDER BY DESC to avoid NULL rows ranking first.
- volume column in p_markets is numeric — can SUM/ORDER directly.
- PNL columns (total_pnl, avg_total_pnl, fifo_total_pnl) can be negative.
- Filter extreme outliers: WHERE avg_total_pnl < 40000000 AND total_bought_cost > 1 (exclude dust/test accounts).
- For ROI: total_pnl / NULLIF(total_bought_cost, 0) — always guard division by zero.
- LIMIT results to 20 rows unless user specifies otherwise.
- SELECT only. Never INSERT/UPDATE/DELETE.
- Use PostgreSQL syntax.
- NEVER use MAX()/MIN() on large tables. Use ORDER BY col DESC LIMIT 1 instead.
- For COUNT(*) on large tables, use pg_class: SELECT reltuples::bigint FROM pg_class WHERE relname = '...'
- Never use SELECT *. Only select the columns you need.
- For JOINs involving large tables, filter BEFORE joining (CTE or subquery to narrow rows first).
- Prefer EXISTS over IN for subqueries on large tables.
- DATA QUALITY: The usd column in trade tables has ~0.006% dirty rows with raw chain values (e.g. 5e18).
  ALWAYS add "WHERE usd < 1000000" when doing SUM(usd)/AVG(usd) to exclude outliers.

═══════════════════════════════════════════
WORKFLOW:
═══════════════════════════════════════════

CRITICAL: You MUST actually execute queries — NEVER just describe what you "would" do.
Every data question requires at least one run_public_sql_query call before giving FINAL_ANSWER.

1. Analyze the user's question — determine which tables are involved.
2. ⚠ CHECK THE LARGE TABLE REGISTRY above. If any target table is listed there, you MUST follow its mandatory strategy. NEVER write a full-scan query on a large table.
3. If you already know the table from the core reference, go straight to step 5 (skip find_tables/get_table_schema).
4. If unsure, call find_tables or get_table_schema to discover schema.
5. Generate SQL — double-check against the LARGE TABLE REGISTRY before executing.
6. Call run_public_sql_query to execute — this step is MANDATORY.
7. If the query fails (timeout or error), analyze the error, rewrite a more efficient SQL, and retry.
8. After receiving query results, give FINAL_ANSWER following the OUTPUT STYLE rules below.

═══════════════════════════════════════════
OUTPUT STYLE (FINAL_ANSWER):
═══════════════════════════════════════════

Write in plain, conversational Chinese. Imagine you are explaining to a non-technical colleague.

STRUCTURE — you MUST follow this exact order:

1. **Voice Summary (语音摘要)**: Start with a `<!-- VOICE_SUMMARY -->` marker, then write 1-3 sentences that summarize the key findings in natural spoken Chinese. This will be read aloud by TTS, so:
   - NO wallet addresses, NO hex strings, NO token IDs
   - NO markdown syntax (no **, no |, no #)
   - Use spoken numbers: "约15亿美元" not "$1,500,000,000"
   - End with `<!-- /VOICE_SUMMARY -->`
   Example: <!-- VOICE_SUMMARY -->交易量最高的市场是关于特朗普能否赢得2024年美国总统选举，交易量约15亿美元，远超其他市场。前五名市场主要集中在政治领域。<!-- /VOICE_SUMMARY -->

2. **Data Table**: Present the detailed results as a Markdown table.
   - Column headers in Chinese
   - Large numbers → readable units ("XX 万美元")
   - Wallet addresses → first 6 + last 4 chars (0x7c3d...5c6b)
   - Percentages → "XX.X%"

3. **Insight** (optional): 1-2 sentences of analysis after the table.

Formatting rules:
- Do NOT include raw SQL in the answer.
- Do NOT repeat tool call details or intermediate steps.
- Token IDs: omit entirely or say "Token #1".

RESPONSE FORMAT:
- Tool call: TOOL_CALL: <tool_name>(<json_args>)
  Examples:
  TOOL_CALL: get_table_schema({"table_name": "p_polymarket_trader_info_mv", "schema": "polymarket"})
  TOOL_CALL: run_public_sql_query({"sql": "SELECT question, volume FROM polymarket.p_markets WHERE active = true ORDER BY volume DESC NULLS LAST LIMIT 5"})

- Final answer: FINAL_ANSWER: <your answer in Chinese>
"""

MAX_AGENT_STEPS = 12  # Safety limit
MAX_SQL_RETRIES = 2  # Allow LLM to fix SQL errors this many times before giving up


# ── Tool dispatch ─────────────────────────────────────────────


async def _dispatch_tool(tool_name: str, args: dict) -> str:
    """Call an MCP tool and return the result as a string."""
    if tool_name == "find_tables":
        result = await mcp_client.find_tables(
            schema=args.get("schema", "polymarket"),
            name_filter=args.get("name_filter", ""),
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    elif tool_name == "get_table_schema":
        result = await mcp_client.get_table_schema(
            table_name=args["table_name"], schema=args.get("schema", "polymarket")
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    elif tool_name == "run_public_sql_query":
        result = await mcp_client.run_public_sql_query(
            sql=args["sql"], limit=args.get("limit", 100)
        )
        return json.dumps(result, ensure_ascii=False, default=str)

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


def _parse_tool_call(response: str) -> tuple[str, dict] | None:
    """Parse a TOOL_CALL line from the LLM response."""
    for line in response.strip().split("\n"):
        line = line.strip()
        if line.startswith("TOOL_CALL:"):
            call_str = line[len("TOOL_CALL:") :].strip()
            # Parse: tool_name({"key": "value"})
            paren_idx = call_str.find("(")
            if paren_idx < 0:
                continue
            tool_name = call_str[:paren_idx].strip()
            args_str = call_str[paren_idx + 1 :].rstrip(")")
            try:
                args = json.loads(args_str)
                return tool_name, args
            except json.JSONDecodeError:
                continue
    return None


def _parse_final_answer(response: str) -> str | None:
    """Extract FINAL_ANSWER from LLM response (supports multi-line answers)."""
    if "FINAL_ANSWER:" not in response:
        return None
    idx = response.index("FINAL_ANSWER:")
    result = response[idx + len("FINAL_ANSWER:") :].strip()
    return result or None


# ── Schema context: auto-discover relevant table columns ──────

# Keyword → table mappings (ordered by relevance)
_KEYWORD_TABLE_MAP: list[tuple[list[str], list[str]]] = [
    # (keywords, [tables to describe])
    (
        ["交易", "trade", "买入", "卖出", "buy", "sell", "最新数据", "latest"],
        ["p_polymarket_trades_with_price_v"],
    ),
    (
        ["pnl", "盈亏", "profit", "loss", "收益", "亏损", "roi"],
        ["p_polymarket_total_pnl_v", "p_polymarket_pnl"],
    ),
    (
        [
            "trader",
            "用户",
            "地址",
            "address",
            "排名",
            "top",
            "smart",
            "胜率",
            "win_rate",
        ],
        ["p_polymarket_trader_info_mv", "p_polymarket_trader_smart"],
    ),
    (["market", "市场", "交易量", "volume", "活跃", "active", "问题"], ["p_markets"]),
    (
        ["event", "事件", "标签", "tag", "分类", "category"],
        ["p_events", "p_polymarket_tags"],
    ),
    (["奖励", "reward", "激励"], ["p_polymarket_rewards"]),
    (
        ["价格", "price", "历史", "history", "趋势", "trend"],
        ["p_polymarket_market_price_history"],
    ),
    (["策略", "strategy", "profile"], ["p_polymarket_trader_info_mv"]),
    (["token", "clob", "映射"], ["p_clobtokens"]),
]


async def _get_schema_context(question: str) -> str:
    """
    Based on user question keywords, auto-describe the most relevant tables.
    Returns a formatted schema block to inject into the agent system prompt.
    Emits pipeline events so the frontend shows 'schema_discovery' status.
    """
    q = question.lower()
    tables_to_describe: list[str] = []
    seen = set()

    for keywords, tables in _KEYWORD_TABLE_MAP:
        if any(kw in q for kw in keywords):
            for t in tables:
                if t not in seen:
                    tables_to_describe.append(t)
                    seen.add(t)

    # Always include p_markets as fallback if nothing matched
    if not tables_to_describe:
        tables_to_describe = ["p_markets", "p_polymarket_trades_with_price_v"]

    # Cap at 4 tables to keep prompt concise
    tables_to_describe = tables_to_describe[:4]

    await emit_start("schema_discovery", {"tables": len(tables_to_describe)})

    lines = ["LIVE SCHEMA (actual column names from database):\n"]
    loaded = 0
    for tname in tables_to_describe:
        try:
            desc = await mcp_client.get_table_schema(tname, schema="polymarket")
            columns = desc.get("columns", [])
            if not columns:
                continue
            loaded += 1
            col_strs = [f"{c['name']} ({c['type']})" for c in columns]
            lines.append(f"  {tname}: {', '.join(col_strs)}")
        except Exception:
            continue

    described_names = [t for t in tables_to_describe[:loaded]]
    await emit_done(
        "schema_discovery",
        result=", ".join(described_names) if described_names else "no tables found",
    )
    return "\n".join(lines) if loaded > 0 else ""


# ── Main agent loop ───────────────────────────────────────────


async def query(question: str) -> dict:
    """
    Full agent loop: question → schema discovery → tool calls → SQL → results → answer.

    Returns: {
        "sql": str,           # The SQL that was executed (if any)
        "rows": list[dict],   # Query results
        "answer": str,        # Natural language answer
        "error": str | None
    }
    """
    # Phase 1: Auto-discover relevant table schemas
    schema_context = await _get_schema_context(question)

    await emit_start("agent.reasoning", {"question": question[:60]})

    system_content = AGENT_SYSTEM.replace(
        "$CURRENT_TIME$",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
    # Inject live schema after the static reference
    if schema_context:
        system_content += f"\n\n{schema_context}\n\nUse the LIVE SCHEMA column names above — they are the ground truth.\n"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": question},
    ]

    last_sql = ""
    last_rows: list[dict] = []
    sql_error_count = 0  # Track consecutive SQL failures

    for step in range(MAX_AGENT_STEPS):
        # Ask LLM for next action
        response = await chat(messages, temperature=0.0)
        messages.append({"role": "assistant", "content": response})

        # Check if LLM wants to call a tool
        tool_call = _parse_tool_call(response)
        if tool_call:
            tool_name, args = tool_call

            # Execute tool
            tool_result = await _dispatch_tool(tool_name, args)

            # Track SQL and results for the return value
            if tool_name == "run_public_sql_query":
                last_sql = args.get("sql", "")
                try:
                    parsed = json.loads(tool_result)
                except Exception:
                    parsed = {}

                if "error" in parsed:
                    err_msg = parsed["error"]
                    sql_error_count += 1

                    if sql_error_count > MAX_SQL_RETRIES:
                        # Exhausted retries — give up
                        await emit_done(
                            "agent.reasoning",
                            result=f"SQL failed after {sql_error_count} attempts",
                        )
                        return {
                            "sql": last_sql,
                            "rows": [],
                            "answer": (
                                f"SQL 经过 {sql_error_count} 次尝试仍然失败：`{err_msg}`\n\n"
                                f"最后执行的 SQL：\n```sql\n{last_sql}\n```\n\n"
                                "请尝试换一种问法或提供更具体的条件。"
                            ),
                            "error": err_msg,
                        }

                    # Feed error back to LLM so it can fix the SQL
                    is_timeout = (
                        "timeout" in err_msg.lower() or "cancel" in err_msg.lower()
                    )
                    if is_timeout:
                        hint = (
                            f"SQL query timed out (attempt {sql_error_count}/{MAX_SQL_RETRIES}). "
                            "The query is too slow. Rewrite it to be faster:\n"
                            "- Use a monthly partition (e.g. poly_trades_d_202604) instead of the full view\n"
                            "- Add tighter WHERE conditions to reduce scan scope\n"
                            "- Use materialized views (p_polymarket_trader_info_mv, p_polymarket_trader_smart) instead of raw tables\n"
                            "- Avoid SUM/COUNT/MAX on the full trades view without strong filters\n"
                            "- Use pg_class reltuples for approximate row counts\n"
                            f"Error: {err_msg}"
                        )
                    else:
                        hint = (
                            f"SQL error (attempt {sql_error_count}/{MAX_SQL_RETRIES}). "
                            f"Fix the query and try again.\nError: {err_msg}"
                        )

                    messages.append({"role": "user", "content": hint})
                    continue

                # Success — reset error counter
                sql_error_count = 0
                columns = parsed.get("columns", [])
                rows = parsed.get("rows", [])
                last_rows = [dict(zip(columns, row)) for row in rows]

            # Feed tool result back to LLM
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool_name}:\n{tool_result}",
                }
            )
            continue

        # Check if LLM has a final answer
        final = _parse_final_answer(response)
        if final:
            await emit_done("agent.reasoning", result=f"Completed in {step + 1} steps")
            return {"sql": last_sql, "rows": last_rows, "answer": final, "error": None}

        # If response doesn't match either pattern:
        # - If we haven't executed any SQL yet, nudge LLM to actually run a query
        # - Otherwise treat as final answer
        if not last_sql and step < MAX_AGENT_STEPS - 2:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You explained what to do but did NOT execute a query. "
                        "Please call run_public_sql_query now with the actual SQL. "
                        'Respond with: TOOL_CALL: run_public_sql_query({"sql": "..."})'
                    ),
                }
            )
            continue

        await emit_done("agent.reasoning", result=f"Completed in {step + 1} steps")
        return {"sql": last_sql, "rows": last_rows, "answer": response, "error": None}

    await emit_done("agent.reasoning", result="Max steps reached")
    return {
        "sql": last_sql,
        "rows": last_rows,
        "answer": "达到最大推理步数限制，请尝试更具体的问题。",
        "error": "Max agent steps reached",
    }


def format_results_as_text(result: dict) -> str:
    """Format query result dict into readable text for display."""
    if result.get("error"):
        return f"Query error: {result['error']}"

    rows = result.get("rows", [])
    if not rows:
        return "No results found."

    cols = list(rows[0].keys())
    lines = [" | ".join(cols)]
    lines.append("-" * len(lines[0]))

    for row in rows[:20]:
        vals = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                vals.append(f"{v:,.2f}")
            else:
                vals.append(str(v) if v is not None else "—")
        lines.append(" | ".join(vals))

    return "\n".join(lines)
