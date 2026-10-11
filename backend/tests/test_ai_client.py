"""OpenAI クライアント — src.ai.client のテスト

実際の API は呼ばず、キー解決・クライアント生成・JSON 応答処理を検証する。
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAIError

from src.ai.client import (
    _clean_api_key,
    _safe_number,
    chat_json,
    get_openai_client,
    resolve_openai_api_key,
)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """OpenAI 関連の環境変数をテストごとに空にする。"""
    for name in ("OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)


class TestCleanApiKey:
    """_clean_api_key() のテスト"""

    def test_strips_whitespace(self):
        """前後の空白を除去すること"""
        assert _clean_api_key("  sk-abc  ") == "sk-abc"

    @pytest.mark.parametrize("quoted", ['"sk-abc"', "'sk-abc'"])
    def test_strips_surrounding_quotes(self, quoted):
        """環境変数に混入した引用符を除去すること"""
        assert _clean_api_key(quoted) == "sk-abc"

    def test_keeps_inner_quotes(self):
        """内部の引用符は残すこと"""
        assert _clean_api_key('sk-a"b') == 'sk-a"b'

    def test_mismatched_quotes_are_kept(self):
        """前後で異なる引用符は除去しないこと"""
        assert _clean_api_key("\"sk-abc'") == "\"sk-abc'"

    def test_empty_string(self):
        """空文字はそのまま返すこと"""
        assert _clean_api_key("   ") == ""


class TestResolveOpenaiApiKey:
    """resolve_openai_api_key() のテスト"""

    def test_prefers_the_settings_value(self, override_settings, monkeypatch):
        """設定値を最優先すること"""
        override_settings(openai_api_key="sk-from-settings")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        assert resolve_openai_api_key() == "sk-from-settings"

    @pytest.mark.parametrize("name", ["OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_API_TOKEN"])
    def test_falls_back_to_environment_variables(self, name, override_settings, monkeypatch):
        """設定が空なら複数の環境変数名を順に探すこと"""
        override_settings(openai_api_key="")
        monkeypatch.setenv(name, "sk-env")
        assert resolve_openai_api_key() == "sk-env"

    def test_environment_precedence(self, override_settings, monkeypatch):
        """OPENAI_API_KEY を他の別名より優先すること"""
        override_settings(openai_api_key="")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-primary")
        monkeypatch.setenv("OPENAI_KEY", "sk-secondary")
        assert resolve_openai_api_key() == "sk-primary"

    def test_returns_empty_when_unset(self, override_settings):
        """どこにも無ければ空文字を返すこと"""
        override_settings(openai_api_key="")
        assert resolve_openai_api_key() == ""

    def test_quoted_values_are_cleaned(self, override_settings):
        """引用符付きの値も正規化されること"""
        override_settings(openai_api_key='"sk-quoted"')
        assert resolve_openai_api_key() == "sk-quoted"


class TestGetOpenaiClient:
    """get_openai_client() のテスト"""

    def test_raises_without_a_key(self, override_settings):
        """キー未設定なら分かりやすいエラーにすること"""
        override_settings(openai_api_key="")
        with pytest.raises(ValueError, match="OPENAI_API_KEY が設定されていません"):
            get_openai_client()

    def test_creates_a_client_with_a_timeout(self, override_settings):
        """タイムアウトを設定したクライアントを返すこと"""
        override_settings(openai_api_key="sk-test")
        with patch("src.ai.client.OpenAI") as openai:
            get_openai_client()

        assert openai.call_args.kwargs["api_key"] == "sk-test"
        assert openai.call_args.kwargs["timeout"] == 90.0


class TestSafeNumber:
    """_safe_number() のテスト"""

    @pytest.mark.parametrize("value,expected", [
        (1.5, 1.5), (2, 2.0), ("3.5", 3.5), ("-1", -1.0),
    ])
    def test_converts_numeric_values(self, value, expected):
        """数値・数値文字列を float へ変換すること"""
        assert _safe_number(value) == expected

    @pytest.mark.parametrize("value", [None, "abc", {}, [], "", "N/A"])
    def test_invalid_values_use_the_default(self, value):
        """変換できない値は既定値を返すこと（AI 応答の揺れを吸収）"""
        assert _safe_number(value) == 0

    def test_custom_default(self):
        """既定値を指定できること"""
        assert _safe_number(None, default=50) == 50


class TestChatJson:
    """chat_json() のテスト"""

    def _client(self, content: str):
        """OpenAI クライアントのモックを組み立てる。"""
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = response
        return client

    def test_parses_the_json_response(self):
        """応答を JSON としてパースして返すこと"""
        client = self._client('{"action": "buy", "confidence": 70}')
        with patch("src.ai.client.get_openai_client", return_value=client):
            assert chat_json("sys", "user") == {"action": "buy", "confidence": 70}

    def test_requests_json_mode(self):
        """JSON モードを指定して呼び出すこと"""
        client = self._client("{}")
        with patch("src.ai.client.get_openai_client", return_value=client):
            chat_json("sys", "user")

        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_sends_system_and_user_messages(self):
        """システム・ユーザーの 2 メッセージを送ること"""
        client = self._client("{}")
        with patch("src.ai.client.get_openai_client", return_value=client):
            chat_json("あなたは FX アナリストです", "USDJPY を分析して")

        messages = client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "あなたは FX アナリストです"}
        assert messages[1] == {"role": "user", "content": "USDJPY を分析して"}

    def test_default_temperature_is_low(self):
        """分析用途のため既定 temperature を低く保つこと"""
        client = self._client("{}")
        with patch("src.ai.client.get_openai_client", return_value=client):
            chat_json("sys", "user")

        assert client.chat.completions.create.call_args.kwargs["temperature"] == 0.3

    def test_temperature_can_be_overridden(self):
        """temperature を指定できること"""
        client = self._client("{}")
        with patch("src.ai.client.get_openai_client", return_value=client):
            chat_json("sys", "user", temperature=0.9)

        assert client.chat.completions.create.call_args.kwargs["temperature"] == 0.9

    def test_uses_the_configured_model(self, override_settings):
        """設定のモデル名を使うこと"""
        override_settings(openai_model="gpt-4o")
        client = self._client("{}")
        with patch("src.ai.client.get_openai_client", return_value=client):
            chat_json("sys", "user")

        assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o"

    def test_empty_content_becomes_an_empty_dict(self):
        """応答が空でも空辞書として扱うこと"""
        client = self._client(None)
        with patch("src.ai.client.get_openai_client", return_value=client):
            assert chat_json("sys", "user") == {}

    def test_api_errors_become_value_errors(self):
        """API エラーは日本語メッセージの ValueError に変換すること"""
        client = MagicMock()
        client.chat.completions.create.side_effect = OpenAIError("rate limit")
        with patch("src.ai.client.get_openai_client", return_value=client):
            with pytest.raises(ValueError, match="OpenAI API エラー"):
                chat_json("sys", "user")

    def test_invalid_json_becomes_a_value_error(self):
        """JSON でない応答は分かりやすいエラーにすること"""
        client = self._client("not json at all")
        with patch("src.ai.client.get_openai_client", return_value=client):
            with pytest.raises(ValueError, match="解析できませんでした"):
                chat_json("sys", "user")

    def test_missing_key_propagates_as_value_error(self, override_settings):
        """キー未設定のエラーもそのまま伝わること"""
        override_settings(openai_api_key="")
        with pytest.raises(ValueError):
            chat_json("sys", "user")
