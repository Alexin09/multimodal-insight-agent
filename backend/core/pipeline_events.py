"""
Pipeline event system for streaming MCP tool-call status to the frontend.

Uses asyncio.Queue to decouple event producers (router, text2sql, mcp_client)
from the SSE consumer (server.py streaming handler).

Each event maps to an Open WebUI `<details type="tool_calls">` block,
rendered as a compact single-line status indicator with spinner → ✓.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from contextvars import ContextVar

# ── Event model ─────────────────────────────────────────────


@dataclass
class ToolEvent:
    """A single tool-call lifecycle event."""

    name: str  # e.g. "mcp.get_table_schema", "mcp.run_public_sql_query"
    done: bool = False
    arguments: str = ""  # JSON-encoded args (shown on expand)
    result: str = ""  # Summary of result (shown on expand)


# ── Per-request event queue (via contextvars) ────────────────

_current_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "_current_queue", default=None
)


def create_event_queue() -> asyncio.Queue:
    """Create and set a new event queue for the current request context."""
    q: asyncio.Queue = asyncio.Queue()
    _current_queue.set(q)
    return q


def get_event_queue() -> Optional[asyncio.Queue]:
    """Get the event queue for the current request context."""
    return _current_queue.get()


async def emit(event: ToolEvent):
    """Push an event to the current request's queue (no-op if no queue)."""
    q = _current_queue.get()
    if q is not None:
        await q.put(event)


async def emit_start(name: str, arguments: dict | str = "") -> None:
    """Convenience: emit a tool-call-started event."""
    args_str = json.dumps(arguments) if isinstance(arguments, dict) else arguments
    await emit(ToolEvent(name=name, done=False, arguments=args_str))


async def emit_done(name: str, result: str = "") -> None:
    """Convenience: emit a tool-call-completed event."""
    await emit(ToolEvent(name=name, done=True, result=result))


# ── Sentinel to signal "all pipeline work is done" ──────────

PIPELINE_DONE = object()


async def emit_pipeline_done():
    """Signal that the pipeline has finished — no more tool events."""
    q = _current_queue.get()
    if q is not None:
        await q.put(PIPELINE_DONE)


# ── Render a ToolEvent as an Open WebUI compatible HTML fragment ──


def render_tool_event(evt: ToolEvent) -> str:
    """
    Render a ToolEvent as a `<details type="tool_calls">` HTML block.

    Open WebUI natively recognizes this format and renders it as a
    compact single-line status indicator:
      - done="false" → spinner animation
      - done="true"  → green checkmark ✓

    Users can click to expand and see arguments/result.
    """
    done_str = "true" if evt.done else "false"
    parts = [f'<details type="tool_calls" name="{evt.name}" done="{done_str}"']
    if evt.arguments:
        # Escape quotes for HTML attribute
        escaped_args = evt.arguments.replace('"', "&quot;")
        parts.append(f' arguments="{escaped_args}"')
    if evt.result:
        escaped_result = evt.result.replace('"', "&quot;")
        parts.append(f' result="{escaped_result}"')
    parts.append(">\n</details>\n")
    return "".join(parts)
