#!/usr/bin/env python3
"""
Offline pipeline tester — run natural language questions through the full
text2sql agent loop, capture every tool event + final result, and dump
structured JSON logs for frontend development reference.

Usage:
    cd backend
    .venv/bin/python test_pipeline.py

Output:
    tmp/pipeline_test_<timestamp>.json
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure backend/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from core.pipeline_events import (
    create_event_queue,
    emit_pipeline_done,
    render_tool_event,
    PIPELINE_DONE,
    ToolEvent,
)
from core.router import classify
from core.text2sql import query as text2sql_query, format_results_as_text


# ── Test questions ────────────────────────────────────────────

TEST_QUESTIONS = [
    # 1. 简单聚合 — p_markets（安全小表）
    "交易量最高的5个市场是什么？",
    # 2. 排行榜 — p_polymarket_trader_smart（安全小表）
    "过去7天盈利最多的前10个地址是哪些？",
    # 3. 用户统计 — p_polymarket_trader_smart（有 win_rate 列）
    "胜率超过80%的聪明交易者有哪些？列出前5个及其总盈亏",
    # 4. 交易者画像 — p_polymarket_trader_info_mv（物化视图）
    "交易天数最多的前5个地址，分别交易了多少天，总盈亏多少？",
    # 5. 当月分区 — poly_trades_d_YYYYMM（应走当月分区）
    "今天有多少笔交易？",
    # 6. PNL 分析 — p_polymarket_trader_smart
    "30天盈利最多的前5个地址的胜率分别是多少？",
    # 7. 奖励查询 — p_polymarket_rewards
    "最近30天获得奖励最多的前5个地址",
    # 8. 闲聊 — general_chat 路径
    "你好，你能帮我做什么？",
]


# ── Core runner ───────────────────────────────────────────────


async def run_one_question(question: str) -> dict:
    """
    Run a single question through the full pipeline.
    Returns a structured log with all tool events + result.
    """
    print(f"\n{'=' * 70}")
    print(f"  Q: {question}")
    print(f"{'=' * 70}")

    record = {
        "question": question,
        "timestamp": datetime.now().isoformat(),
        "tool_events": [],
        "route": None,
        "result": None,
        "timing": {},
    }

    # Phase 1: Intent classification
    t0 = time.time()
    event_queue = create_event_queue()

    route = await classify(question, has_image=False)
    record["route"] = {
        "intent": route.intent,
        "needs_chart": route.needs_chart,
        "needs_tts": route.needs_tts,
        "has_image": route.has_image,
    }
    t_route = time.time() - t0
    record["timing"]["classify_intent"] = round(t_route, 3)
    print(f"  [route] intent={route.intent} ({t_route:.2f}s)")

    # Drain classify events
    while not event_queue.empty():
        evt = event_queue.get_nowait()
        if isinstance(evt, ToolEvent):
            record["tool_events"].append(_event_to_dict(evt))
            _print_event(evt)

    # Phase 2: Text2SQL agent loop (if text_query)
    if route.intent in ("text_query", "mixed"):
        t1 = time.time()

        # Run pipeline as a task so we can drain events concurrently
        pipeline_task = asyncio.create_task(_run_text2sql(question))

        # Drain events while pipeline runs
        while True:
            try:
                evt = await asyncio.wait_for(event_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                if pipeline_task.done():
                    # Final drain
                    while not event_queue.empty():
                        evt = event_queue.get_nowait()
                        if evt is PIPELINE_DONE:
                            break
                        if isinstance(evt, ToolEvent):
                            record["tool_events"].append(_event_to_dict(evt))
                            _print_event(evt)
                    break
                continue

            if evt is PIPELINE_DONE:
                break
            if isinstance(evt, ToolEvent):
                record["tool_events"].append(_event_to_dict(evt))
                _print_event(evt)

        result = await pipeline_task
        t_query = time.time() - t1
        record["timing"]["text2sql"] = round(t_query, 3)
        record["timing"]["total"] = round(time.time() - t0, 3)

        record["result"] = {
            "sql": result.get("sql", ""),
            "row_count": len(result.get("rows", [])),
            "rows_preview": result.get("rows", [])[:5],  # first 5 rows
            "answer": result.get("answer", ""),
            "error": result.get("error"),
        }

        print(f"\n  [sql] {result.get('sql', 'N/A')[:120]}")
        print(f"  [rows] {len(result.get('rows', []))} rows returned")
        print(
            f"  [time] route={t_route:.2f}s  text2sql={t_query:.2f}s  total={time.time() - t0:.2f}s"
        )
        print(f"  [answer] {result.get('answer', '')[:200]}...")

    else:
        record["timing"]["total"] = round(time.time() - t0, 3)
        record["result"] = {
            "intent": route.intent,
            "note": "Not a text_query, skipped agent loop",
        }
        print(f"  [skip] intent={route.intent}, no SQL pipeline")

    return record


async def _run_text2sql(question: str) -> dict:
    """Wrapper that calls text2sql and signals pipeline done."""
    try:
        result = await text2sql_query(question)
        return result
    finally:
        await emit_pipeline_done()


def _event_to_dict(evt: ToolEvent) -> dict:
    """Convert a ToolEvent to a JSON-serializable dict."""
    return {
        "name": evt.name,
        "done": evt.done,
        "arguments": evt.arguments,
        "result": evt.result,
    }


def _print_event(evt: ToolEvent):
    """Pretty-print a single tool event to console."""
    icon = "✓" if evt.done else "⟳"
    args_preview = evt.arguments[:60] if evt.arguments else ""
    result_preview = evt.result[:60] if evt.result else ""
    detail = result_preview if evt.done else args_preview
    print(f"  {icon} {evt.name:35s} {detail}")


# ── Main ──────────────────────────────────────────────────────


async def main():
    print("=" * 70)
    print("  Polydata Insight — Pipeline Test")
    print(
        f"  LLM_MODE={os.getenv('LLM_MODE', 'mock')}  DB_MODE={os.getenv('DB_MODE', 'sqlite')}"
    )
    print(f"  Model={os.getenv('OPENAI_MODEL', 'N/A')}")
    print("=" * 70)

    all_records = []

    for q in TEST_QUESTIONS:
        try:
            record = await run_one_question(q)
            all_records.append(record)
        except Exception as e:
            print(f"\n  ❌ ERROR: {e}")
            all_records.append(
                {
                    "question": q,
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
            )

    # Save results
    out_dir = Path(__file__).resolve().parent.parent / "tmp"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"pipeline_test_{ts}.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"  ✅ Results saved to: {out_file}")
    print(f"  Total questions: {len(all_records)}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
