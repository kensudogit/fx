"""
OpenAI API クライアントモジュール。

このモジュールは OpenAI API との通信に必要な共通機能を提供する。
APIキーの解決（複数の環境変数名に対応）・クライアントの生成・
JSON レスポンスの取得・エラーハンドリングをカプセル化する。

Railway や Docker 等の本番環境では環境変数名が統一されていないケースがあるため、
複数の候補名をフォールバックしながら API キーを取得する仕組みを備えている。
"""

import json
import logging
import os
from typing import Any

from openai import OpenAI, OpenAIError

from src.config import settings

logger = logging.getLogger(__name__)


def _clean_api_key(value: str) -> str:
    """
    API キー文字列から余分な空白・引用符を除去する。

    環境変数に誤ってクォートが含まれている場合（例: '"sk-..."' や "'sk-...'"）に対処する。
    Railway や .env ファイルからの読み込み時にこのような問題が発生しやすい。

    Args:
        value: クリーニング対象の API キー文字列

    Returns:
        str: 先頭・末尾の空白とクォートを除去した API キー文字列
    """
    # 先頭・末尾の空白を除去する
    value = value.strip()
    # 同一のシングル/ダブルクォートで囲まれている場合はクォートを除去する
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def resolve_openai_api_key() -> str:
    """
    Railway 等で複数の環境変数名に対応しながら OpenAI API キーを解決する。

    環境によって API キーの環境変数名が異なるケースに対応するため、
    settings → OPENAI_API_KEY → OPENAI_KEY → OPENAI_API_TOKEN の順で検索する。
    有効なキーが見つかった時点で即座に返す。

    Returns:
        str: 有効な API キー文字列。見つからない場合は空文字を返す。
    """
    # まず settings（アプリ設定）から取得を試みる
    if settings.openai_api_key:
        key = _clean_api_key(settings.openai_api_key)
        if key:
            return key
    # settings に設定がない場合は複数の環境変数名を順番に試す
    # Railway・Docker・ローカル環境などで異なる命名規則に対応するため
    for name in ("OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_API_TOKEN"):
        value = _clean_api_key(os.environ.get(name, ""))
        if value:
            return value
    # どの環境変数にも有効なキーがない場合は空文字を返す
    return ""


def get_openai_client() -> OpenAI:
    """
    設定済みの OpenAI クライアントインスタンスを生成して返す。

    API キーが未設定の場合は ValueError を raise し、呼び出し元に設定不備を通知する。
    timeout=90.0 は大規模なレスポンスや重い処理でもタイムアウトしないよう余裕を持った値。

    Returns:
        OpenAI: 設定済みの OpenAI クライアントインスタンス

    Raises:
        ValueError: OPENAI_API_KEY が設定されていない場合
    """
    api_key = resolve_openai_api_key()
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。Railway の環境変数を確認してください。")
    # timeout=90.0 秒: 分析系の重いプロンプトでも確実に完了できるよう長めに設定する
    return OpenAI(api_key=api_key, timeout=90.0)


def _safe_number(value: Any, default: float = 0) -> float:
    """
    任意の値を安全に float に変換する。

    OpenAI のレスポンスには数値フィールドに文字列・None・不正な型が
    含まれる可能性があるため、変換失敗時はデフォルト値を返す。

    Args:
        value: 変換対象の値（str, int, float, None など任意の型）
        default: 変換失敗時に返すデフォルト値（デフォルト 0）

    Returns:
        float: 変換後の浮動小数点数、または変換失敗時のデフォルト値
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        # None・非数値文字列・変換不可能な型はデフォルト値に置き換える
        return default


def chat_json(system: str, user: str, temperature: float = 0.3) -> dict[str, Any]:
    """
    OpenAI Chat Completion API を呼び出し、JSON レスポンスをパースして返す。

    response_format=json_object を指定することで OpenAI に確実に JSON を返させる。
    temperature=0.3 はデフォルト値として分析系タスクに適した低い値を使用し、
    一貫性のある構造化された出力を促進する。

    Args:
        system: システムプロンプト（AI の役割・出力形式を定義する）
        user: ユーザープロンプト（分析対象のデータや質問）
        temperature: 出力の創造性を制御するパラメータ（0=決定論的, 1=創造的）
                     分析タスクでは低い値（0.3）を使用して再現性を高める

    Returns:
        dict[str, Any]: OpenAI の応答を JSON パースした辞書

    Raises:
        ValueError: OpenAI API エラーまたは JSON パースエラーが発生した場合
    """
    try:
        client = get_openai_client()
        # response_format=json_object を指定して OpenAI に JSON のみを返させる
        # これにより JSON パースエラーの発生確率を大幅に下げられる
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # JSON モードを有効化: OpenAI が必ず有効な JSON を返すことを保証する
            response_format={"type": "json_object"},
            temperature=temperature,
        )
        # レスポンスから本文テキストを取得する（None の場合は空 JSON オブジェクトを使用）
        content = response.choices[0].message.content or "{}"
        # JSON 文字列を Python 辞書に変換して返す
        return json.loads(content)
    except OpenAIError as e:
        # OpenAI API レベルのエラー（認証失敗・レートリミット・サーバーエラー等）
        logger.exception("OpenAI API error")
        raise ValueError(f"OpenAI API エラー: {e}") from e
    except json.JSONDecodeError as e:
        # response_format=json_object でも稀に無効な JSON が返る場合のエラー処理
        logger.exception("OpenAI JSON parse error")
        raise ValueError("OpenAI の応答を解析できませんでした") from e
