"""
Vision module: OCR + VLM image understanding.
Uses GPT-4o Vision in openai mode, mock otherwise.
"""

import os
import base64
from dotenv import load_dotenv
from core.llm_client import chat_with_vision

load_dotenv()

LLM_MODE = os.getenv("LLM_MODE", "mock")


async def analyze_image(
    image_bytes: bytes, question: str = "Describe this image in detail."
) -> str:
    """Analyze an image with optional guiding question. Returns text analysis."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        }
    ]

    return await chat_with_vision(messages)


async def extract_table_from_image(image_bytes: bytes) -> str:
    """Extract tabular data from a screenshot/photo using VLM."""
    prompt = (
        "Extract ALL data from this image into a clean markdown table. "
        "Include column headers. If the image contains a chart, describe "
        "the data points. Output ONLY the markdown table, no explanation."
    )
    return await analyze_image(image_bytes, prompt)


async def describe_chart(image_bytes: bytes) -> str:
    """Describe a chart/graph image — trends, anomalies, key takeaways."""
    prompt = (
        "Analyze this chart/graph image. Describe:\n"
        "1. What type of chart it is\n"
        "2. The key trends or patterns\n"
        "3. Any anomalies or notable data points\n"
        "4. A brief summary conclusion\n"
        "Be concise and data-focused."
    )
    return await analyze_image(image_bytes, prompt)
