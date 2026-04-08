"""
ASR (Automatic Speech Recognition) via Whisper.
Mock mode returns placeholder text; openai mode uses Whisper API.
"""

import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

LLM_MODE = os.getenv("LLM_MODE", "mock")


async def transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Transcribe audio bytes to text."""
    if LLM_MODE == "openai":
        return _transcribe_openai(audio_bytes, filename)
    return _transcribe_mock()


def _transcribe_openai(audio_bytes: bytes, filename: str) -> str:
    from openai import OpenAI

    client = OpenAI()

    # Write to temp file (Whisper API needs a file)
    suffix = Path(filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )
        return result.strip()
    finally:
        os.unlink(tmp_path)


def _transcribe_mock() -> str:
    return "What are the top 5 markets by trading volume?"
