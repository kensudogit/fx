"""OpenAI API クライアント"""

import json
import logging
from typing import Any

from openai import OpenAI

from src.config import settings

logger = logging.getLogger(__name__)


def get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。Railway の環境変数を確認してください。")
    return OpenAI(api_key=settings.openai_api_key)


def chat_json(system: str, user: str, temperature: float = 0.3) -> dict[str, Any]:
    """JSON 形式で応答を取得"""
    client = get_openai_client()
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def chat_text(system: str, user: str, temperature: float = 0.5) -> str:
    client = get_openai_client()
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content or ""
