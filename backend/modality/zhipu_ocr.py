"""
GLM-OCR integration via ZhipuAI layout_parsing API.

Extracts text content from images (base64 or URL) using GLM-OCR.
Falls back gracefully if API key is not configured.
"""

import os
import base64
import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "").strip()
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


async def ocr_from_base64(image_b64: str, mime_type: str = "image/png") -> str:
    """
    Extract text from a base64-encoded image using GLM-OCR.

    Args:
        image_b64: Base64-encoded image data (without data: prefix)
        mime_type: MIME type of the image

    Returns:
        Extracted text content, or empty string on failure.
    """
    if not ZHIPU_API_KEY:
        return ""

    # GLM-OCR accepts base64 as data URI
    data_uri = f"data:{mime_type};base64,{image_b64}"
    return await _call_ocr(data_uri)


async def ocr_from_url(image_url: str) -> str:
    """
    Extract text from an image URL using GLM-OCR.

    Returns:
        Extracted text content, or empty string on failure.
    """
    if not ZHIPU_API_KEY:
        return ""

    return await _call_ocr(image_url)


async def _call_ocr(file_input: str) -> str:
    """Call GLM-OCR layout_parsing API and extract text from results."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ZHIPU_BASE_URL}/layout_parsing",
                headers={
                    "Authorization": f"Bearer {ZHIPU_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "glm-ocr",
                    "file": file_input,
                },
            )

        if resp.status_code != 200:
            print(f"[zhipu_ocr] API error: {resp.status_code} {resp.text[:200]}")
            return ""

        data = resp.json()
        return _extract_text(data)

    except Exception as e:
        print(f"[zhipu_ocr] Error: {e}")
        return ""


def _extract_text(ocr_response: dict) -> str:
    """
    Extract readable text from GLM-OCR layout_parsing response.

    The response contains layout_details with labeled blocks.
    We extract text/title blocks and join them in reading order.
    """
    texts = []

    # layout_details is a list of pages, each page is a list of blocks
    for page in ocr_response.get("layout_details", []):
        for block in page:
            label = block.get("label", "")
            content = block.get("content", "")
            if content and label in ("text", "title", "header", "footer", "caption"):
                texts.append(content.strip())

    # Also check markdown_content (some responses include full markdown)
    md = ocr_response.get("markdown_content", "")
    if md and not texts:
        return md.strip()

    return "\n".join(texts)


async def ocr_to_query_intent(image_b64: str, mime_type: str = "image/png") -> str:
    """
    Full pipeline: image → OCR → extract user intent as a query question.

    If the image contains data/charts/tables, formulates a data question.
    If it contains general text, returns the text for LLM to interpret.
    """
    ocr_text = await ocr_from_base64(image_b64, mime_type)
    if not ocr_text:
        return ""

    return ocr_text
