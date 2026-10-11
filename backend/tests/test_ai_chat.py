"""AI 投資相談チャット — src.ai.chat のテスト

DB と OpenAI はモックへ差し替え、セッション管理・履歴・エラー処理を検証する。
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.ai.chat import (
    ChatMessage,
    ChatSession,
    _save_message,
    chat,
    get_messages,
    init_chat_tables,
    list_sessions,
)


@pytest.fixture(autouse=True)
def no_table_init():
    """テーブル初期化は DB へ触れるため無効化する。"""
    with patch("src.ai.chat.init_chat_tables"):
        yield


def session_row(**kwargs):
    """ChatSession 相当のスタブ。"""
    defaults = dict(id=1, symbol="USDJPY", title="USDJPY の戦略",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def message_row(role="user", content="こんにちは"):
    """ChatMessage 相当のスタブ。"""
    return SimpleNamespace(role=role, content=content,
                           created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def scalars_session(rows):
    """execute().scalars().all() が rows を返すモックセッション。"""
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = rows
    return session


class TestTableDefinitions:
    """ORM テーブル定義のテスト"""

    def test_session_table_name(self):
        """セッションテーブル名が chat_sessions であること"""
        assert ChatSession.__tablename__ == "chat_sessions"

    def test_message_table_name(self):
        """メッセージテーブル名が chat_messages であること"""
        assert ChatMessage.__tablename__ == "chat_messages"

    def test_session_is_tenant_scoped(self):
        """セッションがテナントに紐づくこと"""
        assert "tenant_id" in {c.name for c in ChatSession.__table__.columns}

    def test_message_links_to_a_session(self):
        """メッセージがセッションに紐づくこと"""
        assert "session_id" in {c.name for c in ChatMessage.__table__.columns}

    def test_message_has_role_and_content(self):
        """メッセージが役割と本文を持つこと"""
        columns = {c.name for c in ChatMessage.__table__.columns}
        assert {"role", "content", "created_at"} <= columns


class TestInitChatTables:
    """init_chat_tables() のテスト"""

    def test_swallows_database_errors(self):
        """DB へ接続できなくても例外を送出しないこと"""
        with patch("src.ai.chat.init_chat_tables", wraps=init_chat_tables), \
             patch.object(ChatSession.__table__, "create", side_effect=OSError("no db")):
            init_chat_tables()  # 例外が出なければ成功


class TestListSessions:
    """list_sessions() のテスト"""

    def test_maps_rows_to_dicts(self):
        """セッション行を辞書へ変換すること"""
        with patch("src.ai.chat.SessionLocal", return_value=scalars_session([session_row()])):
            sessions = list_sessions(tenant_id=1)

        assert sessions[0]["id"] == 1
        assert sessions[0]["symbol"] == "USDJPY"
        assert sessions[0]["title"] == "USDJPY の戦略"

    def test_timestamps_are_iso_strings(self):
        """作成日時を ISO 文字列で返すこと"""
        with patch("src.ai.chat.SessionLocal", return_value=scalars_session([session_row()])):
            assert isinstance(list_sessions(1)[0]["created_at"], str)

    def test_missing_timestamp_is_none(self):
        """作成日時が無ければ None を返すこと"""
        with patch("src.ai.chat.SessionLocal",
                   return_value=scalars_session([session_row(created_at=None)])):
            assert list_sessions(1)[0]["created_at"] is None

    def test_empty_result(self):
        """セッションが無ければ空リストを返すこと"""
        with patch("src.ai.chat.SessionLocal", return_value=scalars_session([])):
            assert list_sessions(1) == []

    def test_closes_the_session(self):
        """DB セッションを閉じること"""
        session = scalars_session([])
        with patch("src.ai.chat.SessionLocal", return_value=session):
            list_sessions(1)
        session.close.assert_called_once()

    def test_filters_by_tenant(self):
        """テナントで絞り込むこと（他テナントの会話を見せない）"""
        session = scalars_session([])
        with patch("src.ai.chat.SessionLocal", return_value=session):
            list_sessions(tenant_id=42)

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert "42" in compiled


class TestGetMessages:
    """get_messages() のテスト"""

    def test_maps_rows_to_dicts(self):
        """メッセージ行を辞書へ変換すること"""
        rows = [message_row("user", "質問"), message_row("assistant", "回答")]
        with patch("src.ai.chat.SessionLocal", return_value=scalars_session(rows)):
            messages = get_messages(1)

        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "質問"

    def test_empty_result(self):
        """メッセージが無ければ空リストを返すこと"""
        with patch("src.ai.chat.SessionLocal", return_value=scalars_session([])):
            assert get_messages(1) == []

    def test_scoped_to_the_session(self):
        """指定セッションのメッセージのみを引くこと"""
        session = scalars_session([])
        with patch("src.ai.chat.SessionLocal", return_value=session):
            get_messages(session_id=7)

        compiled = str(session.execute.call_args[0][0].compile(
            compile_kwargs={"literal_binds": True}))
        assert "7" in compiled


class TestSaveMessage:
    """_save_message() のテスト"""

    def test_adds_without_committing(self):
        """追加のみ行い、コミットは呼び出し元に委ねること"""
        db = MagicMock()
        _save_message(db, 1, "user", "こんにちは")

        db.add.assert_called_once()
        db.commit.assert_not_called()

    def test_records_role_and_content(self):
        """役割と本文を記録すること"""
        db = MagicMock()
        _save_message(db, 5, "assistant", "回答本文")

        msg = db.add.call_args[0][0]
        assert msg.session_id == 5
        assert msg.role == "assistant"
        assert msg.content == "回答本文"
        assert msg.created_at.tzinfo is timezone.utc


class TestChat:
    """chat() のテスト"""

    def _openai_client(self, reply="AI の回答"):
        message = MagicMock()
        message.content = reply
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = response
        return client

    def test_requires_an_api_key(self):
        """API キー未設定なら設定を促すメッセージを返すこと"""
        with patch("src.ai.chat.resolve_openai_api_key", return_value=""):
            result = asyncio.run(chat("質問"))

        assert result["error"] == "openai_not_configured"
        assert "OPENAI_API_KEY" in result["reply"]

    def test_creates_a_session_when_none_is_given(self):
        """セッション ID 未指定なら新規作成すること"""
        db = MagicMock()

        def flush():
            db.add.call_args[0][0].id = 99

        db.flush.side_effect = flush
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=self._openai_client()), \
             patch("src.ai.chat.get_messages", return_value=[]):
            result = asyncio.run(chat("USDJPY の戦略を教えて", symbol="usdjpy", tenant_id=1))

        created = db.add.call_args_list[0][0][0]
        assert created.symbol == "USDJPY"
        assert created.title == "USDJPY の戦略を教えて"
        assert result["session_id"] == 99

    def test_title_is_truncated(self):
        """セッション名は 60 文字までに切り詰めること"""
        db = MagicMock()
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=self._openai_client()), \
             patch("src.ai.chat.get_messages", return_value=[]):
            asyncio.run(chat("あ" * 200))

        assert len(db.add.call_args_list[0][0][0].title) == 60

    def test_unknown_session_returns_an_error(self):
        """存在しないセッション ID ならエラーを返すこと"""
        db = MagicMock()
        db.get.return_value = None
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db):
            result = asyncio.run(chat("質問", session_id=999))

        assert "セッションが見つかりません" in result["reply"]
        db.rollback.assert_called_once()

    def test_returns_the_reply_and_history(self):
        """AI の返答と会話履歴を返すこと"""
        db = MagicMock()
        history = [{"role": "user", "content": "質問"}, {"role": "assistant", "content": "回答"}]
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client",
                   return_value=self._openai_client("押し目買いを推奨します")), \
             patch("src.ai.chat.get_messages", return_value=history):
            result = asyncio.run(chat("質問", session_id=1))

        assert result["reply"] == "押し目買いを推奨します"
        assert result["messages"] == history

    def test_system_prompt_mentions_the_symbol_and_education(self):
        """システムプロンプトに対象通貨ペアと教育目的の注意を含めること"""
        db = MagicMock()
        client = self._openai_client()
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=client), \
             patch("src.ai.chat.get_messages", return_value=[]):
            asyncio.run(chat("質問", symbol="EURUSD", session_id=1))

        system = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "EURUSD" in system
        assert "教育目的" in system

    def test_recent_history_is_sent(self):
        """直近 10 件までの履歴をモデルへ渡すこと"""
        db = MagicMock()
        client = self._openai_client()
        history = [{"role": "user", "content": f"msg{i}"} for i in range(30)]
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=client), \
             patch("src.ai.chat.get_messages", return_value=history):
            asyncio.run(chat("質問", session_id=1))

        messages = client.chat.completions.create.call_args.kwargs["messages"]
        # システムプロンプト + 直近 10 件
        assert len(messages) == 11

    def test_persists_both_sides_of_the_conversation(self):
        """ユーザー発言と AI 返答の両方を保存してコミットすること"""
        db = MagicMock()
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=self._openai_client()), \
             patch("src.ai.chat.get_messages", return_value=[]), \
             patch("src.ai.chat._save_message") as save:
            asyncio.run(chat("質問", session_id=1))

        roles = [c[0][2] for c in save.call_args_list]
        assert roles == ["user", "assistant"]
        db.commit.assert_called_once()

    def test_openai_errors_are_returned_not_raised(self):
        """OpenAI のエラーは例外にせずメッセージとして返すこと"""
        db = MagicMock()
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", side_effect=RuntimeError("rate limit")), \
             patch("src.ai.chat.get_messages", return_value=[]):
            result = asyncio.run(chat("質問", session_id=1))

        assert "rate limit" in result["error"]
        db.rollback.assert_called_once()

    def test_empty_reply_is_handled(self):
        """AI の返答が空でも例外にならないこと"""
        db = MagicMock()
        with patch("src.ai.chat.resolve_openai_api_key", return_value="sk-test"), \
             patch("src.ai.chat.SessionLocal", return_value=db), \
             patch("src.ai.chat.get_openai_client", return_value=self._openai_client(None)), \
             patch("src.ai.chat.get_messages", return_value=[]):
            assert asyncio.run(chat("質問", session_id=1))["reply"] == ""
