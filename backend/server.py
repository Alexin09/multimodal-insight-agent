"""
FastAPI server exposing OpenAI-compatible API endpoints.
Open WebUI connects to this as a custom model provider.

Endpoints:
  POST /v1/chat/completions   — main chat (Text2SQL + multimodal)
  POST /v1/audio/transcriptions — Whisper ASR
  GET  /v1/models              — model listing (for Open WebUI discovery)
  GET  /health                 — health check
"""

import os
import json
import time
import uuid
import base64
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
    FileResponse,
    HTMLResponse,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from core.router import classify
from core.text2sql import query as text2sql_query, format_results_as_text
from core.llm_client import chat
from core.db import get_connection  # ensure DB is initialized on startup
from core.pipeline_events import (
    create_event_queue,
    emit_pipeline_done,
    render_tool_event,
    PIPELINE_DONE,
    ToolEvent,
)
from modality.asr import transcribe
from modality.tts import synthesize
from modality.vision import analyze_image, extract_table_from_image
from modality.chart import generate_chart

app = FastAPI(title="HermoResearch.ai", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_ID = "hermoresearch-ai"
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


# ── Pydantic models ───────────────────────────────────────────


class ChatMessage(BaseModel):
    role: str
    content: str | list  # str for text, list for multimodal content


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]
    temperature: float = 0.0
    stream: bool = False
    max_tokens: Optional[int] = None


# ── Startup ───────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    get_connection().close()
    print(f"✓ Database initialized")
    print(f"✓ LLM mode: {os.getenv('LLM_MODE', 'mock')}")
    print(f"✓ Server ready — OpenAI-compatible API at /v1/")


# ── Models endpoint (Open WebUI discovery) ────────────────────


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "multimodal-insight-agent",
                "permission": [],
            }
        ],
    }


@app.get("/")
async def home():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse(
        "<h3>HermoResearch.ai</h3><p>API is ready at <code>/v1/*</code>.</p>"
    )


# ── Chat completions ─────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    Main endpoint. Handles:
    1. Text queries → Text2SQL → results → formatted response
    2. Image + text → VLM analysis
    3. General chat → direct LLM

    When streaming, tool-call status events are injected into the SSE
    stream in real-time as `<details type="tool_calls">` blocks that
    Open WebUI renders as compact single-line indicators with spinner → ✓.
    """
    # Extract the last user message
    last_msg = request.messages[-1] if request.messages else None
    if not last_msg:
        return _error_response("No messages provided")

    user_text, image_bytes = _extract_content(last_msg)

    if request.stream:
        # Real-time streaming: pipeline runs concurrently with SSE output
        return StreamingResponse(
            _stream_with_tool_events(user_text, image_bytes),
            media_type="text/event-stream",
        )

    # Non-streaming: run pipeline synchronously, return final result
    # (still create event queue so pipeline_events don't error out)
    create_event_queue()
    route = await classify(user_text, has_image=image_bytes is not None)

    if route.intent == "vision_analysis":
        response_text = await _handle_vision(image_bytes, user_text)
    elif route.intent == "mixed":
        response_text = await _handle_mixed(image_bytes, user_text, route)
    elif route.intent == "text_query":
        response_text = await _handle_text_query(user_text, route)
    else:
        response_text = await _handle_general(user_text)

    return _chat_response(response_text)


# ── Audio transcription ──────────────────────────────────────


@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default="whisper-1"),
):
    audio_bytes = await file.read()
    text = await transcribe(audio_bytes, file.filename or "audio.wav")
    return {"text": text}


# ── TTS endpoint ─────────────────────────────────────────────


@app.post("/v1/audio/speech")
async def audio_speech(request: Request):
    body = await request.json()
    text = body.get("input", "")
    voice = body.get("voice", "en-US-AriaNeural")

    audio_bytes = await synthesize(text, voice)
    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "attachment; filename=speech.mp3"},
    )


# ── Health check ─────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_ID, "mode": os.getenv("LLM_MODE", "mock")}


# ── Pipeline handlers ────────────────────────────────────────


async def _handle_text_query(user_text: str, route) -> str:
    """Text → Agent loop (discover schema → SQL → execute → summarize)."""
    result = await text2sql_query(user_text)

    if result.get("error") and not result.get("answer"):
        return f"⚠️ Query error: {result['error']}\n\nGenerated SQL:\n```sql\n{result.get('sql', 'N/A')}\n```"

    # Agent already provides a natural language answer
    answer = result.get("answer", "")
    sql = result.get("sql", "")
    rows = result.get("rows", [])
    table_text = format_results_as_text(result) if rows else ""

    # Build response — LLM answer already contains formatted table + insight.
    # Do NOT append raw query results or SQL (they leak internal details).
    parts = [answer]

    # If chart-worthy, generate and encode
    if route.needs_chart and rows:
        chart_bytes = generate_chart(rows)
        if chart_bytes:
            b64_chart = base64.b64encode(chart_bytes).decode()
            parts.append(f"\n![Chart](data:image/png;base64,{b64_chart})")

    return "\n".join(parts)


async def _handle_vision(image_bytes: bytes, user_text: str) -> str:
    """
    Image upload handler:
    1. Try GLM-OCR to extract text from image
    2. If OCR finds text → treat as user query intent → route to text2sql/general
    3. If no text → fallback to VLM visual analysis
    """
    from modality.zhipu_ocr import ocr_from_base64
    import base64

    # Step 1: OCR the image
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    ocr_text = await ocr_from_base64(b64)

    if ocr_text and len(ocr_text.strip()) > 5:
        # OCR found meaningful text — use it as the query
        # Combine user text (if any) with OCR-extracted text
        if user_text and user_text.strip():
            query = f"{user_text}\n\n以下是从图片中识别的内容：\n{ocr_text}"
        else:
            query = (
                f"以下是从上传图片中识别的文字内容，请理解其意图并回答：\n\n{ocr_text}"
            )

        # Route the OCR text through the normal pipeline
        route = await classify(query, has_image=False)
        if route.intent == "text_query":
            return await _handle_text_query(query, route)
        else:
            return await _handle_general(query)

    # Fallback: no text found, use VLM for visual analysis
    analysis = await analyze_image(
        image_bytes, user_text or "Analyze this image in detail."
    )
    return f"**图片分析：**\n\n{analysis}"


async def _handle_mixed(image_bytes: bytes, user_text: str, route) -> str:
    """Image + text query → OCR + Text2SQL → combined response."""
    from modality.zhipu_ocr import ocr_from_base64
    import base64

    # OCR the image first
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    ocr_text = await ocr_from_base64(b64)

    # Combine user text with OCR content
    if ocr_text and len(ocr_text.strip()) > 5:
        combined_query = f"{user_text}\n\n图片中识别的内容：\n{ocr_text}"
    else:
        combined_query = user_text

    # Run text2sql with the combined query
    sql_result = await text2sql_query(combined_query)

    parts = []
    if ocr_text:
        parts.append(
            f"**图片识别内容：**\n{ocr_text[:200]}{'...' if len(ocr_text) > 200 else ''}"
        )
        parts.append("")

    if sql_result.get("answer"):
        parts.append(sql_result["answer"])
    elif sql_result.get("error"):
        parts.append(f"⚠️ 查询出错：{sql_result.get('error')}")

    return "\n".join(parts)


async def _handle_general(user_text: str) -> str:
    """General chat — direct LLM response."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are HermoResearch.ai, a prediction market data research assistant. "
                "You can answer data questions using SQL, analyze images, "
                "generate charts, and provide voice output. "
                "If the user asks a data question, tell them you'll query the database. "
                "Be helpful and concise."
            ),
        },
        {"role": "user", "content": user_text},
    ]
    return await chat(messages, temperature=0.5)


# ── Helpers ──────────────────────────────────────────────────


def _extract_content(msg: ChatMessage) -> tuple[str, bytes | None]:
    """Extract text and optional image bytes from a chat message."""
    if isinstance(msg.content, str):
        return msg.content, None

    # Multimodal content (list of parts)
    text_parts = []
    image_bytes = None

    for part in msg.content:
        if isinstance(part, dict):
            if part.get("type") == "text":
                text_parts.append(part["text"])
            elif part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    # data:image/png;base64,xxx
                    b64_data = url.split(",", 1)[1] if "," in url else ""
                    image_bytes = base64.b64decode(b64_data)

    return " ".join(text_parts), image_bytes


def _chat_response(content: str) -> dict:
    """Format as OpenAI-compatible chat completion response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _run_pipeline(user_text: str, image_bytes: bytes | None) -> str:
    """Execute the full pipeline, emitting events along the way."""
    route = await classify(user_text, has_image=image_bytes is not None)

    if route.intent == "vision_analysis":
        result = await _handle_vision(image_bytes, user_text)
    elif route.intent == "mixed":
        result = await _handle_mixed(image_bytes, user_text, route)
    elif route.intent == "text_query":
        result = await _handle_text_query(user_text, route)
    else:
        result = await _handle_general(user_text)

    await emit_pipeline_done()
    return result


async def _stream_with_tool_events(user_text: str, image_bytes: bytes | None):
    """
    Real-time SSE generator that interleaves tool-call status events
    with the final response content.

    Architecture:
      1. Create an asyncio.Queue for pipeline events
      2. Launch the pipeline as a background task
      3. While pipeline runs, drain events from the queue and
         yield them as `<details type="tool_calls">` content chunks
      4. When pipeline finishes, stream the final response word-by-word

    Rendering strategy (append-only, SSE compatible):
      Since SSE content is append-only (message.content += delta), we cannot
      update an already-sent `done="false"` to `done="true"`. Instead:

      - "start" events are NOT rendered immediately — we hold them in a
        pending set so the user sees a spinner effect via the next approach.
      - "done" events emit a `<details type="tool_calls" done="true">` block.
        This gives each completed tool a green ✓ in Open WebUI.
      - While the pipeline is still working, we emit a `<status>` element
        that Open WebUI renders as a shimmer-animated single-line indicator
        showing what's currently running. This `<status>` is appended once
        at the start and the name shown is the latest pending tool.

      The final visual in Open WebUI:
        ✓ classify_intent              ← completed tool (green check, 1 line)
        ✓ mcp.schema_discovery         ← completed tool
        ✓ llm.text_to_sql              ← completed tool
        ✓ mcp.run_public_sql_query     ← completed tool
        (actual answer streams below)
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    event_queue = create_event_queue()

    # Launch pipeline in background
    pipeline_task = asyncio.create_task(_run_pipeline(user_text, image_bytes))

    # Only these 3 top-level steps are shown to the user;
    # sub-events (mcp.get_table_schema, mcp.run_public_sql_query, mcp.find_tables) are hidden.
    VISIBLE_STEPS = {"classify_intent", "schema_discovery", "agent.reasoning"}

    def _yield_chunk(content: str) -> str:
        """Format a content delta as an SSE chunk string."""
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
        return f"data: {json.dumps(chunk)}\n\n"

    # Real-time streaming: push each visible step's start/done event immediately
    rendered_starts: set[str] = set()
    rendered_dones: set[str] = set()

    while True:
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            if pipeline_task.done():
                # Drain remaining
                while not event_queue.empty():
                    event = event_queue.get_nowait()
                    if event is PIPELINE_DONE:
                        break
                    if isinstance(event, ToolEvent) and event.name in VISIBLE_STEPS:
                        if not event.done and event.name not in rendered_starts:
                            rendered_starts.add(event.name)
                            yield _yield_chunk(render_tool_event(event))
                        elif event.done and event.name not in rendered_dones:
                            rendered_dones.add(event.name)
                            yield _yield_chunk(render_tool_event(event))
                break
            continue

        if event is PIPELINE_DONE:
            break

        if isinstance(event, ToolEvent) and event.name in VISIBLE_STEPS:
            if not event.done and event.name not in rendered_starts:
                rendered_starts.add(event.name)
                yield _yield_chunk(render_tool_event(event))
            elif event.done and event.name not in rendered_dones:
                rendered_dones.add(event.name)
                yield _yield_chunk(render_tool_event(event))

    # Phase 3: Get pipeline result and stream it word-by-word
    response_text = await pipeline_task

    # Clean up LLM artifacts for better readability
    if response_text.startswith("FINAL_ANSWER:"):
        response_text = response_text[len("FINAL_ANSWER:") :].lstrip("\n ")

    words = response_text.split(" ")
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        yield _yield_chunk(token)
        await asyncio.sleep(0.02)  # simulate typing

    # Final chunk
    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_chunks(content: str):
    """Yield SSE chunks for streaming response (legacy, non-event version)."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    words = content.split(" ")
    for i, word in enumerate(words):
        token = word + (" " if i < len(words) - 1 else "")
        chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.02)

    final = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


def _error_response(message: str):
    return JSONResponse(
        status_code=400,
        content={"error": {"message": message, "type": "invalid_request_error"}},
    )


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=True)
