"""AI チャット（投資相談）"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, desc, select

from src.ai.client import get_openai_client, resolve_openai_api_key
from src.config import settings
from src.db.database import Base, SessionLocal, engine

_memory_sessions: dict[int, list[dict]] = {}
_session_counter = 0


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    symbol = Column(String(10), default="USDJPY")
    title = Column(String(120), default="投資相談")
    created_at = Column(DateTime(timezone=True), nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


def init_chat_tables():
    try:
        ChatSession.__table__.create(engine, checkfirst=True)
        ChatMessage.__table__.create(engine, checkfirst=True)
    except Exception:
        pass


def list_sessions(tenant_id: int | None, limit: int = 20) -> list[dict]:
    init_chat_tables()
    db = SessionLocal()
    try:
        q = select(ChatSession).order_by(desc(ChatSession.created_at)).limit(limit)
        if tenant_id is not None:
            q = q.where(ChatSession.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "title": r.title,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


def get_messages(session_id: int, limit: int = 50) -> list[dict]:
    init_chat_tables()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .limit(limit)
        ).scalars().all()
        return [
            {"role": r.role, "content": r.content, "created_at": r.created_at.isoformat()}
            for r in rows
        ]
    finally:
        db.close()


def _save_message(db, session_id: int, role: str, content: str):
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)


async def chat(
    message: str,
    symbol: str = "USDJPY",
    session_id: int | None = None,
    tenant_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    if not resolve_openai_api_key():
        return {
            "session_id": session_id or 0,
            "reply": "OpenAI API キーが未設定です。Railway の OPENAI_API_KEY を設定してください。",
            "error": "openai_not_configured",
        }

    init_chat_tables()
    db = SessionLocal()
    try:
        if not session_id:
            session = ChatSession(
                tenant_id=tenant_id,
                user_id=user_id,
                symbol=symbol.upper(),
                title=message[:60],
                created_at=datetime.now(timezone.utc),
            )
            db.add(session)
            db.flush()
            session_id = session.id
        else:
            session = db.get(ChatSession, session_id)
            if not session:
                raise ValueError("セッションが見つかりません")

        _save_message(db, session_id, "user", message)
        history = get_messages(session_id, 20)

        system = (
            "あなたはFX投資の専門アドバイザーです。"
            f"現在の相談通貨ペア: {symbol}。"
            "日本語で簡潔かつ実用的に回答。具体的な価格は参考値として述べ、"
            "投資助言ではなく教育目的である旨を必要に応じて伝えてください。"
            "リスク管理・テクニカル・ファンダメンタルの観点をバランスよく含めてください。"
        )
        messages = [{"role": "system", "content": system}]
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})

        client = get_openai_client()
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.5,
                max_tokens=1200,
            )
        )
        reply = response.choices[0].message.content or ""
        _save_message(db, session_id, "assistant", reply)
        db.commit()

        return {
            "session_id": session_id,
            "symbol": symbol.upper(),
            "reply": reply,
            "messages": get_messages(session_id, 50),
        }
    except Exception as e:
        db.rollback()
        return {"session_id": session_id, "reply": f"エラー: {e}", "error": str(e)}
    finally:
        db.close()
