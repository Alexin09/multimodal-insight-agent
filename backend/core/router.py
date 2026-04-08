"""
Intent router: classifies user input and dispatches to the right pipeline.

Pipelines:
  text_query      → Text2SQL → result table → (optional chart) → text response
  vision_analysis → VLM/OCR → LLM analysis → text response
  mixed           → vision + text2sql combined
  general_chat    → direct LLM response
"""

import json
from dataclasses import dataclass, field
from core.llm_client import chat
from core.pipeline_events import emit_start, emit_done

ROUTER_SYSTEM = """You are an intent classifier for a multimodal data analysis assistant.

Given a user message, classify it into one of these intents and output valid JSON only:

{
  "intent": "text_query" | "vision_analysis" | "mixed" | "general_chat",
  "needs_chart": true | false,
  "needs_tts": true | false
}

Rules:
- "text_query": user asks a data question that can be answered with SQL
- "vision_analysis": user uploads an image and asks about it (no SQL needed)
- "mixed": user uploads an image AND asks a data question (needs both vision + SQL)
- "general_chat": greeting, help, or non-data questions
- "needs_chart": true if user explicitly asks for chart/graph/plot/visualization OR the query involves trends/time series
- "needs_tts": true if user explicitly asks for audio/voice/speech output

Output ONLY the JSON, no explanation.
"""


@dataclass
class RoutingResult:
    intent: str = "text_query"
    needs_chart: bool = False
    needs_tts: bool = False
    has_image: bool = False


async def classify(user_text: str, has_image: bool = False) -> RoutingResult:
    """Classify user intent from message text and optional image flag."""
    await emit_start(
        "classify_intent", {"text": user_text[:50], "has_image": has_image}
    )

    # Fast-path: if image is present
    if has_image:
        text_lower = user_text.lower()

        # If user typed text alongside the image → always treat as mixed (OCR + query)
        # Only pure image upload (no text) goes to vision_analysis
        if user_text.strip():
            result = RoutingResult(
                intent="mixed",
                needs_chart=_wants_chart(text_lower),
                needs_tts=_wants_tts(text_lower),
                has_image=True,
            )
            await emit_done("classify_intent", result=f"intent={result.intent}")
            return result

        # Image only, no text → vision_analysis (OCR → auto-detect intent)
        result = RoutingResult(
            intent="vision_analysis",
            needs_chart=False,
            needs_tts=False,
            has_image=True,
        )
        await emit_done("classify_intent", result=f"intent={result.intent}")
        return result

    # LLM-based classification for text-only
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    raw = await chat(messages, temperature=0.0)

    try:
        parsed = json.loads(raw)
        result = RoutingResult(
            intent=parsed.get("intent", "text_query"),
            needs_chart=parsed.get("needs_chart", False),
            needs_tts=parsed.get("needs_tts", False),
            has_image=False,
        )
        await emit_done("classify_intent", result=f"intent={result.intent}")
        return result
    except json.JSONDecodeError:
        # Fallback: keyword-based
        text_lower = user_text.lower()
        if any(w in text_lower for w in ["hello", "hi", "help", "你好"]):
            result = RoutingResult(intent="general_chat")
            await emit_done("classify_intent", result=f"intent={result.intent}")
            return result
        result = RoutingResult(
            intent="text_query",
            needs_chart=_wants_chart(text_lower),
            needs_tts=_wants_tts(text_lower),
        )
        await emit_done("classify_intent", result=f"intent={result.intent}")
        return result


def _wants_chart(text: str) -> bool:
    return any(
        w in text
        for w in ["chart", "graph", "plot", "visualize", "trend", "图表", "趋势"]
    )


def _wants_tts(text: str) -> bool:
    return any(
        w in text
        for w in ["voice", "audio", "speak", "read aloud", "tts", "语音", "播报"]
    )
