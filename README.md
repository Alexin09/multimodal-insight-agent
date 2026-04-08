<div align="center">

# MultiModal Insight Agent

### 💬 Text · 🎤 Voice · 📷 Vision → MCP Tools → Database Insight

A full-stack **multimodal AI agent**: any input modality — **natural language**, **voice**, or **image** — is unified into an **LLM agentic loop** that orchestrates **MCP tool calls** (`find_tables` → `get_schema` → `run_sql`) to query real databases, then streams back structured results with auto-generated charts and voice narration.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![MCP](https://img.shields.io/badge/MCP-Tool_Use-purple)](https://modelcontextprotocol.io/)
[![JavaScript](https://img.shields.io/badge/Vanilla_JS-ES2022-F7DF1E?logo=javascript&logoColor=black)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<br/>

<img src="docs/demo-voice-query.jpg" alt="MultiModal Insight Agent — Voice → MCP → Results" width="720"/>

</div>

---

## Core Idea: Any Modality → MCP → Insight

> **Three input modalities, one unified MCP tool chain, one intelligent answer.**

```
  💬 Type          🎤 Speak           📷 Snap
    │                │                  │
    │           Whisper ASR        GLM-OCR / Vision
    │                │                  │
    └────────────────┴──────────────────┘
                     │
              ┌──────▼──────┐
              │ Intent Router│  LLM classifies intent
              └──────┬──────┘
                     │
              ┌──────▼──────────────────────┐
              │   MCP Tool Chain (3 tools)   │
              │                              │
              │   1. find_tables()           │
              │   2. get_table_schema()      │
              │   3. run_public_sql_query()  │
              └──────┬──────────────────────┘
                     │
              ┌──────▼──────┐
              │  SSE Stream  │  3-step progress + word-by-word
              └──────┬──────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    📊 Auto Chart  📝 Answer   🔊 TTS
```

| Modality | Pipeline | MCP Involvement |
|:---:|:---|:---|
| **💬 Text** | Natural language → Intent Router → **Text2SQL Agent Loop** → MCP `find_tables` → `get_schema` → LLM generates SQL → MCP `run_sql_query` → results + insight | **Full 3-tool chain** |
| **🎤 Voice** | Browser mic → Whisper ASR → transcribed text → **same MCP pipeline as Text** | **Full 3-tool chain** (voice is transparent) |
| **📷 Image (OCR)** | Upload/paste → GLM-OCR extracts text → re-routed as text_query → **MCP pipeline** | **Full 3-tool chain** (OCR → text → MCP) |
| **📷 Image (Vision)** | No text found → GPT-4o Vision analyzes chart/photo directly | Vision LLM (no MCP) |
| **🔀 Mixed** | Image + text → OCR extracts context + user question → **combined MCP query** | **Full 3-tool chain** (multimodal fusion) |

The output flows back as **SSE stream** with a real-time 3-step progress indicator, then word-by-word response rendering — the user watches the agent *think*.

---

## Demo — Multimodal Scenarios

<table>
<tr>
<td width="50%"><img src="docs/demo-voice-query.jpg" alt="Voice Query + MCP"/><br/><em>🎤 Voice input → Whisper ASR → MCP tool chain → table results</em></td>
<td width="50%"><img src="docs/demo-ocr-query.jpg" alt="OCR Query + MCP"/><br/><em>📷 Image OCR → GLM-OCR extract → MCP pipeline → user data analysis</em></td>
</tr>
</table>

---

## Why This Project?

Most "chat with your database" demos are **text-only** and **single-shot**. Real-world data workflows need **multimodal input** funneled through **reliable tool orchestration**:

| Gap in existing demos | How this project solves it |
|:---|:---|
| Text-only input | **3 modalities** — type, speak, or snap a screenshot |
| Single LLM call | **MCP agentic loop** — multi-step: discover schema → generate SQL → execute → auto-retry → summarize |
| Black-box response | **SSE streaming with 3-step progress** — user watches each MCP tool call in real-time |
| Toy SQLite | **Production PostgreSQL** via MCP tools — read-only safety enforced |
| No multimodal fusion | **Mixed mode** — image OCR context + user text question → combined MCP query |
| No output modality | **Auto chart** (matplotlib) + **TTS narration** (edge-tts) |

**MultiModal Insight Agent** = multimodal input layer + LLM intent router + MCP tool chain + streaming output — in one self-contained full-stack application.

---

## Multimodal → MCP Pipeline Deep Dive

Every modality ultimately converges on the **same MCP tool chain**. This is the key design principle.

### 🎤 Voice → MCP

```
Browser mic (WebRTC MediaRecorder)
  → audio blob → POST /v1/audio/transcriptions
  → Whisper ASR → transcribed text
  → ⚡ enters the same pipeline as typing
  → Intent Router → MCP find_tables → get_schema → run_sql_query
```

Voice is a **transparent input adapter** — after Whisper transcription, the text hits the exact same MCP agent loop as direct typing. Zero special handling.

### 📷 Image → MCP

```
Paste / Upload image → base64
  → POST /v1/chat/completions (multimodal)
  │
  ├── GLM-OCR layout_parsing → extracted text?
  │   ├── YES → re-route as text_query → ⚡ MCP tool chain
  │   └── NO  → GPT-4o Vision (chart/photo analysis, no MCP)
  │
  └── Mixed mode (image + user text):
      → OCR extracts context + user question
      → combined query → ⚡ MCP tool chain
```

**Key insight**: OCR converts image into text, which then enters the MCP pipeline — the agent doesn't know the query originated from an image.

### 💬 Text → MCP (Core Agent Loop)

```
"What are the top markets by volume?"
  → Intent Router (LLM classify → text_query)
  │
  → MCP Agent Loop (max 12 steps):
  │   Step 1: MCP find_tables()         → discover available tables
  │   Step 2: MCP get_table_schema()    → column definitions + types
  │   Step 3: LLM generates SQL         → SELECT ... FROM ... 
  │   Step 4: MCP run_public_sql_query()→ execute (read-only enforced)
  │   Step 5: Error? LLM fixes SQL      → auto-retry (max 2)
  │   Step 6: LLM summarizes results    → natural language answer
  │
  → Optional: auto-chart (matplotlib bar/line/hbar)
```

### 🔊 MCP Results → Voice (TTS Output)

```
Agent answer → click 🔊 → POST /v1/audio/speech
  → edge-tts (zh-CN-XiaoxiaoNeural) → MP3 stream → browser playback
```

`getVoiceText()` strips markdown/code/tables, extracts a voice-friendly summary for narration.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                       Browser (Frontend)                      │
│                                                               │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  │
│  │   Text   │   │  Voice   │   │  Image   │   │   Chat   │  │
│  │  Input   │   │ 🎤 Mic   │   │ 📷 Paste │   │    UI    │  │
│  │          │   │ Whisper  │   │  Upload  │   │          │  │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘  │
│       │              │              │               │         │
│       └──────────────┴──────────────┴───────────────┘         │
│                          │ SSE + fetch                        │
└──────────────────────────┼────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │     serve.py (:3210)    │
              │  Static + /v1/* proxy   │
              │  Raw-socket SSE fwd     │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  FastAPI Backend (:8000) │
              │                         │
              │  ┌─────────────────┐    │
              │  │  Intent Router  │    │
              │  │  (LLM classify) │    │
              │  └───┬───┬───┬────┘    │
              │      │   │   │          │
              │  ┌───▼┐ ┌▼──┐ ┌▼─────┐  │
              │  │Text│ │VLM│ │Mixed │  │
              │  │2SQL│ │OCR│ │Query │  │
              │  └─┬──┘ └─┬─┘ └──┬───┘  │
              │    │      │      │       │
              │  ┌─▼──────▼──────▼────┐  │
              │  │    MCP Tools       │  │
              │  │  find_tables       │  │
              │  │  get_table_schema  │  │
              │  │  run_sql_query     │  │
              │  └────────┬───────────┘  │
              │           │              │
              │  ┌────────▼───────────┐  │
              │  │ PostgreSQL / SQLite│  │
              │  └────────────────────┘  │
              │                         │
              │  ┌── Modality Layer ──┐  │
              │  │ 🎤 ASR (Whisper)   │  │
              │  │ 🔊 TTS (edge-tts)  │  │
              │  │ 👁️ Vision (GPT-4o)  │  │
              │  │ 📄 OCR (GLM-OCR)   │  │
              │  │ 📊 Chart (mpl)     │  │
              │  └────────────────────┘  │
              └─────────────────────────┘
```

---

## Features

### Multimodal Input → MCP → Output

| Modality | Direction | Flow | Reaches MCP? |
|:---|:---:|:---|:---:|
| **💬 Text** | Input | Natural language → Intent Router → Text2SQL Agent → MCP 3-tool chain | ✅ Full |
| **🎤 Voice** | Input | Mic → Whisper ASR → text → **same MCP pipeline** | ✅ Full |
| **📷 Image OCR** | Input | Image → GLM-OCR → extracted text → re-route → **MCP pipeline** | ✅ Full |
| **📷 Image Vision** | Input | Image → GPT-4o Vision → chart/photo analysis | ❌ Vision only |
| **🔀 Mixed** | Input | Image + text → OCR context + question → **combined MCP query** | ✅ Full |
| **📊 Chart** | Output | MCP query rows → matplotlib auto-chart (bar/line/hbar) | Post-MCP |
| **🔊 Speech** | Output | MCP answer → edge-tts neural synthesis → MP3 playback | Post-MCP |

### MCP Tool Chain (Core)

| Tool | Function | Safety |
|:---|:---|:---|
| `find_tables()` | Discover all available tables in the database | Read-only |
| `get_table_schema()` | Get column names, types, and constraints for a table | Read-only |
| `run_public_sql_query()` | Execute SQL and return rows (max 500) | **Read-only enforced** — no INSERT/UPDATE/DELETE |

The agent calls these tools in a **loop** (max 12 steps, 2 auto-retries on SQL error), guided by an LLM that decides which tool to call next based on the conversation history.

### Backend Capabilities

| Capability | Description |
|:---|:---|
| **Text2SQL Agent** | LLM-driven agentic loop: analyze → MCP discover schema → generate SQL → MCP execute → auto-retry on error → summarize |
| **Intent Router** | LLM classifier dispatches to `text_query` / `vision_analysis` / `mixed` / `general_chat` — determines MCP involvement |
| **OCR → MCP Bridge** | GLM-OCR extracts text → intent re-routing → transparently enters MCP pipeline |
| **SSE + MCP Events** | Each MCP tool call emits `start`/`done` events → real-time 3-step progress in frontend |
| **Dual DB Mode** | `sqlite` for local demo (zero config), `mcp` for production PostgreSQL |
| **Mock Mode** | Full pipeline works without any API key (`LLM_MODE=mock`) |

### Frontend

| Feature | Description |
|:---|:---|
| **Zero Build** | Pure HTML/CSS/JS — no npm, no bundler, instant startup |
| **SSE Client** | ReadableStream-based parser with incremental DOM updates |
| **3-Step Progress** | Live per-step indicator: ⏳ 理解问题 → ✓ 分析数据结构 → ✓ 查询与分析 |
| **Voice Recording** | In-browser mic capture → Whisper transcription → auto-fill input |
| **Image Upload** | Paste from clipboard or file picker → preview → multimodal API call |
| **Multi-Session** | Create, pin, search, switch conversations |
| **Dark-First UI** | CSS custom properties, particle animations, 3D logo |

---

## Quick Start

### 1. Clone & Configure

```bash
git clone https://github.com/anthropic-alex/multimodal-insight-agent.git
cd multimodal-insight-agent

# Create your config (contains API keys — never committed)
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
# === Minimal config (works immediately) ===
LLM_MODE=mock        # No API key needed for demo!
DB_MODE=sqlite       # Local demo database included

# === Full config (real LLM + OCR) ===
LLM_MODE=openai
OPENAI_BASE_URL=https://api.moonshot.cn/v1
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=kimi-k2.5

# OCR — enables image text extraction (optional)
ZHIPU_API_KEY=your-zhipu-api-key-here
```

### 2. One-Command Start

```bash
chmod +x start.sh
./start.sh
```

This will:
1. Create a Python venv and install dependencies (first run only)
2. Start the FastAPI backend on `:8000`
3. Start the frontend proxy on `:3210`

Open **http://localhost:3210** — that's it.

### 3. Manual Start (Alternative)

```bash
# Terminal 1: Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py

# Terminal 2: Frontend proxy
python3 serve.py
```

---

## Try It

| What to try | How |
|:---|:---|
| **Text query** | Type "What are the top 5 markets by volume?" → watch the 3-step progress → get results |
| **Voice input** | Click the 🎤 mic button → speak your question → release → auto-transcribed and sent |
| **Image OCR** | Screenshot a data table → paste (Ctrl+V) into chat → OCR extracts text → auto-queries |
| **Image analysis** | Upload a chart screenshot → GPT-4o Vision describes trends and anomalies |
| **TTS playback** | After getting a response, click the 🔊 button → hear the answer read aloud |
| **Chart generation** | Ask "Show the trading volume trend" → auto-generated chart in response |

---

## Project Structure

```
multimodal-insight-agent/
├── index.html                    # SPA shell — sidebar nav, 4 pages
├── styles.css                    # Dark-theme design system
├── app.js                        # Page routing, sessions, settings, market UI
├── chat.js                       # SSE client, tool-call parser, ASR/TTS, markdown
├── serve.py                      # HTTP proxy with raw-socket SSE forwarding
├── logo.png                      # App logo
├── start.sh                      # One-command launcher
│
├── backend/
│   ├── server.py                 # FastAPI — /v1/chat/completions, /v1/audio/*, /health
│   ├── requirements.txt          # Python dependencies
│   ├── .env.example              # Config template (API keys, DB credentials)
│   │
│   ├── core/                     # ← Agent brain
│   │   ├── router.py             #   LLM intent classification (4 intents)
│   │   ├── text2sql.py           #   Agent loop: schema → SQL → execute → summarize
│   │   ├── llm_client.py         #   OpenAI client with mock/real dual mode
│   │   ├── mcp_client.py         #   MCP tool wrappers with pipeline event emission
│   │   ├── pipeline_events.py    #   AsyncIO event queue for SSE tool-call streaming
│   │   └── db.py                 #   DB abstraction: SQLite (demo) or PostgreSQL (MCP)
│   │
│   ├── mcp/                      # ← MCP tool chain (the core)
│   │   ├── tools.py              #   3 tools: find_tables, get_schema, run_sql
│   │   └── db.py                 #   PostgreSQL connection + read-only safety
│   │
│   ├── modality/                 # ← Multimodal adapters (all feed into MCP)
│   │   ├── asr.py                #   🎤 Whisper ASR → text → MCP
│   │   ├── tts.py                #   🔊 edge-tts (MCP results → voice)
│   │   ├── vision.py             #   👁️ GPT-4o Vision analysis
│   │   ├── zhipu_ocr.py          #   📄 GLM-OCR → text → MCP
│   │   └── chart.py              #   📊 matplotlib (MCP results → chart)
│
│
├── showcase/                     # Static demo page (multimodal scenarios)
│   ├── index.html                #   Chat UI with 5 demo conversations
│   └── ocr-input.png             #   Sample OCR input image
│
├── docs/                         # Screenshots for README
└── LICENSE
```

---

## How It Works

### Multimodal → MCP Pipeline Flow

```
  💬 Text        🎤 Voice          📷 Image           🔀 Image + Text
    │              │                  │                     │
    │         Whisper ASR         GLM-OCR              OCR + user text
    │              │                  │                     │
    │              ▼                  ▼                     ▼
    │         transcribed         extracted text       combined query
    │           text                  │                     │
    └──────────────┴──────────────────┴─────────────────────┘
                                  │
                   ┌──────────────▼──────────────┐
                   │  Intent Router (LLM classify)│
                   │  → text_query | mixed |      │
                   │    vision_analysis | general  │
                   └──────────────┬──────────────┘
                                  │
                   ┌──────────────▼──────────────┐
                   │   MCP Agent Loop (LLM)       │
                   │   max 12 steps, 2 retries    │
                   │                              │
                   │   1. MCP find_tables()       │──→ available tables
                   │   2. MCP get_table_schema()  │──→ columns + types
                   │   3. LLM generates SQL       │
                   │   4. MCP run_sql_query()     │──→ execute + rows
                   │   5. SQL error? LLM fixes    │──→ retry
                   │   6. LLM summarizes          │──→ answer
                   └──────────────┬──────────────┘
                                  │
                   ┌──────────────▼──────────────┐
                   │  SSE Stream to Frontend       │
                   │  ✓ 理解问题                   │
                   │  ✓ 分析数据结构               │
                   │  ✓ 查询与分析                 │
                   └──────────────┬──────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              📊 Auto Chart   📝 Answer    🔊 TTS
```

### SSE + MCP Event Streaming

The streaming pipeline is the project's core innovation — **every MCP tool call is visible to the user in real-time**:

1. **Backend** — `asyncio.Queue` decouples MCP tool events from SSE output
2. **MCP events** — each tool call (`find_tables`, `get_schema`, `run_sql`) emits `start`/`done` events
3. **SSE generator** — drains the queue, yielding `<details type="tool_calls">` blocks as OpenAI-compatible chunks
4. **Proxy** — `serve.py` dechunks `Transfer-Encoding: chunked` at the TCP level (raw socket, zero buffering)
5. **Frontend** — `ReadableStream` parses SSE, renders 3-step MCP progress:
   ```
   ✓ 理解问题          ← classify_intent done
   ✓ 分析数据结构      ← MCP schema_discovery done
   🔄 查询与分析...     ← MCP agent.reasoning in progress
   ```

Result: the user sees each MCP tool call **in real-time** as the agent thinks.

---

## Supported LLM Providers

Any OpenAI-compatible API works. Tested with:

| Provider | `OPENAI_BASE_URL` | `OPENAI_MODEL` |
|:---|:---|:---|
| **Kimi (Moonshot)** | `https://api.moonshot.cn/v1` | `kimi-k2.5` |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o` |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` |
| **Ollama** | `http://localhost:11434/v1` | `llama3.1` |
| **vLLM** | `http://localhost:8000/v1` | Your model |
| **Mock** | *(any)* | Set `LLM_MODE=mock` |

---

## Tech Stack

| Layer | Technology | Why |
|:---|:---|:---|
| **Backend** | FastAPI + Uvicorn | Async-native, SSE streaming, OpenAI-compatible API surface |
| **LLM** | OpenAI Python SDK | Universal client for any compatible provider |
| **Database** | PostgreSQL (SQLAlchemy) / SQLite | Production + local demo modes |
| **MCP Tools** | Custom 3-tool chain | Schema discovery + safe read-only SQL execution |
| **ASR** | OpenAI Whisper | Industry-standard multilingual speech recognition |
| **TTS** | edge-tts | Free neural voice synthesis — 50+ voices, no API key |
| **OCR** | ZhipuAI GLM-OCR | High-quality layout-parsing OCR (Chinese + English) |
| **Vision** | GPT-4o Vision | Chart analysis, table extraction, image understanding |
| **Charts** | matplotlib | Auto-generated PNG charts from query results |
| **Frontend** | Vanilla JS (ES2022) | Zero dependencies, instant load, full control |
| **Styling** | CSS Custom Properties | Dark theme system, smooth animations |
| **Proxy** | Python raw sockets | SSE chunked transfer dechunking at TCP level |

---

## Configuration Reference

### `backend/.env`

| Variable | Default | Description |
|:---|:---|:---|
| `LLM_MODE` | `mock` | `mock` for demo (no API key), `openai` for real LLM |
| `OPENAI_BASE_URL` | — | LLM API base URL |
| `OPENAI_API_KEY` | — | LLM API key |
| `OPENAI_MODEL` | `gpt-4o` | Model name |
| `ZHIPU_API_KEY` | — | ZhipuAI key for GLM-OCR image text extraction (optional) |
| `DB_MODE` | `sqlite` | `sqlite` for local demo, `mcp` for PostgreSQL |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | — | Database name |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_SCHEMA` | `public` | PostgreSQL schema |
| `QUERY_TIMEOUT` | `60` | SQL query timeout (seconds) |
| `MAX_ROWS` | `500` | Max rows returned per query |
| `PORT` | `8000` | Backend server port |

---

## Extending

### Add New MCP Tools

1. Add the tool function in `backend/mcp/tools.py`
2. Wrap it in `backend/core/mcp_client.py` with event emission
3. Register it in the agent system prompt in `backend/core/text2sql.py`
4. Add a UI card in `app.js` → `MCP_TOOLS` array
5. Add a display name in `chat.js` → `STEP_NAMES`

### Connect Your Own Database

1. Set `DB_MODE=mcp` in `.env`
2. Fill in your PostgreSQL credentials
3. Update the agent system prompt in `text2sql.py` with your table descriptions

### Add New Modalities

The `backend/modality/` directory is designed as a plugin layer:
- Each file exposes async functions with a consistent interface
- `server.py` orchestrates them based on the intent router's decision
- Add a new file (e.g., `pdf.py`) and wire it into `server.py`

---

## Roadmap

- [ ] Persistent sessions with IndexedDB
- [ ] ECharts integration for richer interactive visualizations
- [ ] File upload (CSV/Excel) for ad-hoc analysis
- [ ] Multi-language UI (i18n)
- [ ] Docker Compose for one-click deployment
- [ ] Conversation memory with RAG
- [ ] PDF document parsing modality

---

## License

[MIT](LICENSE) — use it, fork it, ship it.

---

<div align="center">

**Any modality in → MCP tool chain → database insight out.**

*Text, Voice, Vision — unified through MCP `find_tables` → `get_schema` → `run_sql` — streamed back with charts and voice.*

</div>
