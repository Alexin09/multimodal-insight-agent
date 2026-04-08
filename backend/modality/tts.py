"""
TTS (Text-to-Speech) via edge-tts (free, no API key).
Falls back to mock (returns silence) when edge-tts is unavailable.
"""

import asyncio
import tempfile
import os
from pathlib import Path

# Default voice — Chinese female, warm and natural
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


async def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Convert text to speech, return MP3 bytes."""
    try:
        return await _synthesize_edge(text, voice)
    except ImportError:
        return _synthesize_mock()


async def _synthesize_edge(text: str, voice: str) -> bytes:
    import edge_tts

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def _synthesize_mock() -> bytes:
    """Return minimal valid MP3 header as placeholder."""
    # 1-second silence MP3 frame (mock)
    return b"\xff\xfb\x90\x00" + b"\x00" * 417
