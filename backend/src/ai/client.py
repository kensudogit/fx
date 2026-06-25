"""OpenAI API クライアント"""

import json
import logging
import os
from typing import Any

from openai import OpenAI, OpenAIError

from src.config import settings

logger = logging.getLogger(__name__)


def _clean_api_key(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def resolve_openai_api_key() -> str:
    """Railway 等で複数の環境変数名に対応"""
    if settings.openai_api_key:
        key = _clean_api_key(settings.openai_api_key)
        if key:
            return key
    for name in ("OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_API_TOKEN"):
        value = _clean_api_key(os.environ.get(name, ""))
        if value:
            return value
    return ""


def get_openai_client() -> OpenAI:
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。Railway の環境変数を確認してください。")
    return OpenAI(api_key=api_key, timeout=90.0)


def _safe_number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def chat_json(system: str, user: str, temperature: float = 0.3) -> dict[str, Any]:
    try:
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
    except OpenAIError as e:
        logger.exception("OpenAI API error")
        raise ValueError(f"OpenAI API エラー: {e}") from e
    except json.JSONDecodeError as e:
        logger.exception("OpenAI JSON parse error")
        raise ValueError("OpenAI の応答を解析できませんでした") from e
