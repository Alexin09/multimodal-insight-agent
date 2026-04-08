"""
LLM client with mock / openai dual mode.
Toggle via LLM_MODE env var: "mock" (default) or "openai".
"""

import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

LLM_MODE = os.getenv("LLM_MODE", "mock")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DB_MODE = os.getenv("DB_MODE", "sqlite")

# ── OpenAI client (lazy init) ─────────────────────────────────

_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI()  # reads OPENAI_API_KEY from env
    return _openai_client


# ── Public API ─────────────────────────────────────────────────


async def chat(messages: list[dict], temperature: float = 0.0) -> str:
    """Send messages to LLM and return assistant text."""
    if LLM_MODE == "openai":
        return _chat_openai(messages, temperature)
    return _chat_mock(messages)


async def chat_with_vision(messages: list[dict], temperature: float = 0.0) -> str:
    """Send messages that may contain image_url content to VLM."""
    if LLM_MODE == "openai":
        return _chat_openai(messages, temperature)
    return _chat_mock_vision(messages)


# ── OpenAI implementation ─────────────────────────────────────


def _chat_openai(messages: list[dict], temperature: float) -> str:
    client = _get_openai()
    kwargs = dict(model=OPENAI_MODEL, messages=messages)
    # kimi-k2.5 only allows temperature=1; skip the parameter for kimi models
    if not OPENAI_MODEL.startswith("kimi-"):
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


# ── Mock implementation ────────────────────────────────────────


def _chat_mock(messages: list[dict]) -> str:
    """Deterministic mock that handles Text2SQL and general queries."""
    last_msg = messages[-1]["content"] if messages else ""

    # If system prompt asks for SQL generation, return mock SQL
    system_text = ""
    for m in messages:
        if m.get("role") == "system":
            system_text += m.get("content", "")

    if "route" in system_text.lower() or "intent" in system_text.lower():
        return _mock_route(last_msg)

    if "generate a single valid SELECT query" in system_text:
        return _mock_text2sql(last_msg)

    if "data analyst" in system_text.lower() and "query result" in system_text.lower():
        return _mock_summary(last_msg)

    return f"[Mock LLM] Received query: {last_msg[:100]}. In production this would be answered by GPT-4o."


def _mock_text2sql(query: str) -> str:
    """Return plausible SQL for common query patterns."""
    q = query.lower()

    if DB_MODE == "mcp":
        if "volume" in q and ("top" in q or "highest" in q or "most" in q):
            return (
                "SELECT question, volume FROM polymarket.p_markets "
                "WHERE active = true ORDER BY volume DESC NULLS LAST LIMIT 5"
            )

        if "win" in q and "rate" in q:
            return (
                "SELECT address, win_rate, total_pnl, pnl_7d "
                "FROM polymarket.p_polymarket_trader_smart "
                "ORDER BY win_rate DESC NULLS LAST LIMIT 10"
            )

        if "pnl" in q or "profit" in q:
            return (
                "SELECT address, total_pnl, pnl_30d, specialty_tag "
                "FROM polymarket.p_polymarket_trader_smart "
                "ORDER BY total_pnl DESC NULLS LAST LIMIT 10"
            )

        if "price" in q and ("trend" in q or "history" in q):
            return (
                "SELECT t, p, outcome FROM polymarket.p_polymarket_market_price_history "
                "ORDER BY t DESC LIMIT 50"
            )

        if "active" in q and "market" in q:
            return (
                "SELECT question, market_type, volume FROM polymarket.p_markets "
                "WHERE active = true ORDER BY volume DESC NULLS LAST LIMIT 20"
            )

        if "category" in q or "categories" in q:
            return (
                "SELECT market_type, COUNT(*) AS count, SUM(volume) AS total_volume "
                "FROM polymarket.p_markets "
                "GROUP BY market_type ORDER BY total_volume DESC NULLS LAST LIMIT 20"
            )

        if "trader" in q and "count" in q:
            return (
                "SELECT COUNT(*) AS unique_traders FROM polymarket.p_polymarket_users"
            )

        return (
            "SELECT question, market_type, active, volume "
            "FROM polymarket.p_markets ORDER BY volume DESC NULLS LAST LIMIT 10"
        )

    if "volume" in q and ("top" in q or "highest" in q or "most" in q):
        return (
            "SELECT title, total_volume FROM markets ORDER BY total_volume DESC LIMIT 5"
        )

    if "win" in q and "rate" in q:
        return "SELECT addr, win_rate, total_pnl, num_trades FROM traders ORDER BY win_rate DESC LIMIT 10"

    if "pnl" in q or "profit" in q:
        return "SELECT addr, total_pnl, win_rate, num_trades FROM traders ORDER BY total_pnl DESC LIMIT 10"

    if "price" in q and ("trend" in q or "history" in q):
        return "SELECT date, yes_price, volume FROM daily_snapshots WHERE market_id = 1 ORDER BY date"

    if "active" in q and "market" in q:
        return "SELECT title, category, total_volume FROM markets WHERE status = 'active' ORDER BY total_volume DESC"

    if "category" in q or "categories" in q:
        return "SELECT category, COUNT(*) as count, SUM(total_volume) as total_vol FROM markets GROUP BY category ORDER BY total_vol DESC"

    if "trader" in q and "count" in q:
        return "SELECT COUNT(DISTINCT trader_addr) as unique_traders FROM trades"

    # Default
    return "SELECT title, category, status, total_volume FROM markets ORDER BY total_volume DESC LIMIT 10"


def _mock_summary(prompt: str) -> str:
    """Return a concise NL summary for SQL result analysis prompts."""
    row_lines: list[str] = []
    in_results = False

    for line in prompt.splitlines():
        line = line.strip()
        if line.startswith("Results:"):
            in_results = True
            continue
        if not in_results or not line or line.startswith("SQL:"):
            continue
        if line.startswith("---") or line.startswith("```"):
            continue
        if "|" in line:
            row_lines.append(line)

    if len(row_lines) >= 2:
        first = row_lines[1]
        return f"根据当前结果，排名第一的是 {first}。整体上头部数据明显高于其他项，建议继续按时间或类型做细分比较。"

    return "查询已完成。建议继续限定时间范围或分组维度，以获得更有解释力的趋势结论。"


def _mock_route(query: str) -> str:
    """Mock intent routing."""
    q = query.lower()
    if any(w in q for w in ["chart", "graph", "plot", "visualize", "trend"]):
        return json.dumps({"intent": "query_with_chart", "needs_chart": True})
    if any(w in q for w in ["image", "screenshot", "picture", "photo", "ocr"]):
        return json.dumps({"intent": "vision_analysis", "needs_vision": True})
    return json.dumps({"intent": "text_query", "needs_chart": False})


def _chat_mock_vision(messages: list[dict]) -> str:
    """Mock VLM response for image inputs."""
    return (
        "[Mock VLM] Image analysis: The uploaded image appears to contain a data table "
        "with 5 columns and 12 rows. Key observations: values show an upward trend "
        "in the rightmost column. In production this would be analyzed by GPT-4o Vision."
    )
