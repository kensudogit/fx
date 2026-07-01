"""
AI チャット（投資相談）モジュール。

このモジュールは FX 投資に関するユーザーの質問に OpenAI GPT が回答する
対話型チャット機能を提供する。会話履歴はデータベースに永続化され、
セッションをまたいだ文脈のある対話が可能になる。
DB 接続に失敗した場合はメモリ内セッション（_memory_sessions）へのフォールバックを想定している。
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, desc, select

from src.ai.client import get_openai_client, resolve_openai_api_key
from src.config import settings
from src.db.database import Base, SessionLocal, engine

# メモリ内セッションストレージ（DB 不使用または DB 障害時の一時的なフォールバック用）
_memory_sessions: dict[int, list[dict]] = {}
# メモリ内セッション ID のカウンター（DB の autoincrement 代替）
_session_counter = 0


class ChatSession(Base):
    """
    チャットセッションを管理するデータベースモデル。

    ひとつのセッションはユーザーとAIの一連の会話スレッドを表す。
    テナント・ユーザー単位で会話を分離するためのマルチテナント対応構造を持つ。

    Attributes:
        id: セッションの一意識別子（自動採番）
        tenant_id: テナント ID（マルチテナント分離用、NULL 許容）
        user_id: ユーザー ID（ユーザー別の会話管理用、NULL 許容）
        symbol: 相談対象の通貨ペア（例: "USDJPY"）
        title: セッションのタイトル（最初のメッセージ先頭 60 文字）
        created_at: セッション作成日時（UTC タイムゾーン付き）
    """

    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    symbol = Column(String(10), default="USDJPY")
    title = Column(String(120), default="投資相談")
    created_at = Column(DateTime(timezone=True), nullable=False)


class ChatMessage(Base):
    """
    チャットメッセージを管理するデータベースモデル。

    セッション内の個々の発言を記録する。role によってユーザー発言と AI 返答を区別する。
    会話履歴として OpenAI API に渡すために時系列順で取得される。

    Attributes:
        id: メッセージの一意識別子（自動採番）
        session_id: 所属するセッションの ID（ChatSession.id への参照）
        role: 発言者の役割（"user" または "assistant"）
        content: メッセージの本文テキスト
        created_at: メッセージ作成日時（UTC タイムゾーン付き）
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


def init_chat_tables():
    """
    チャット用テーブルをデータベースに作成する（既存の場合はスキップ）。

    アプリ起動時やチャット機能の初回利用時に呼び出す。
    checkfirst=True を指定することで、テーブルが既存の場合は CREATE をスキップし、
    本番運用中の誤削除を防止する。エラーは無視し、呼び出し元の処理を中断しない。
    """
    try:
        # checkfirst=True: テーブルが既に存在する場合は CREATE をスキップする
        ChatSession.__table__.create(engine, checkfirst=True)
        ChatMessage.__table__.create(engine, checkfirst=True)
    except Exception:
        # テーブル作成失敗は致命的エラーではないため握りつぶす
        # （接続エラー時は後続の DB 操作でエラーが発生するため問題なし）
        pass


def list_sessions(tenant_id: int | None, limit: int = 20) -> list[dict]:
    """
    チャットセッション一覧を新しい順で取得する。

    Args:
        tenant_id: テナント ID（None の場合は全テナントを対象とする）
        limit: 取得する最大件数（デフォルト 20）

    Returns:
        list[dict]: セッション情報のリスト（各要素: id・symbol・title・created_at）
    """
    # テーブルが存在しない場合に備えて毎回初期化チェックを行う
    init_chat_tables()
    db = SessionLocal()
    try:
        # 作成日時の降順で取得し、最新のセッションを先頭に表示する
        q = select(ChatSession).order_by(desc(ChatSession.created_at)).limit(limit)
        # テナント ID が指定されている場合は該当テナントのみに絞り込む
        if tenant_id is not None:
            q = q.where(ChatSession.tenant_id == tenant_id)
        rows = db.execute(q).scalars().all()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "title": r.title,
                # datetime オブジェクトを ISO 8601 文字列に変換して JSON レスポンスに適合させる
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        # 例外発生時でも確実にコネクションを返却するために finally ブロックを使用する
        db.close()


def get_messages(session_id: int, limit: int = 50) -> list[dict]:
    """
    指定セッションのメッセージ一覧を時系列順で取得する。

    OpenAI API への履歴渡しと、フロントエンドへの表示の両方に使用される。
    時系列昇順（古い順）で取得することで、会話の流れを保持する。

    Args:
        session_id: 取得対象のセッション ID
        limit: 取得する最大件数（デフォルト 50）

    Returns:
        list[dict]: メッセージのリスト（各要素: role・content・created_at）
    """
    init_chat_tables()
    db = SessionLocal()
    try:
        rows = db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            # 古いメッセージから順に取得して会話の時系列を保持する
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
    """
    チャットメッセージをデータベースセッションに追加する（コミットは呼び出し元で行う）。

    トランザクション管理を呼び出し元（`chat` 関数）に委ねることで、
    セッション作成とメッセージ保存を一つのトランザクションにまとめることができる。

    Args:
        db: SQLAlchemy のデータベースセッション
        session_id: メッセージを属させるセッションの ID
        role: 発言者の役割（"user" または "assistant"）
        content: メッセージ本文テキスト
    """
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        # UTC タイムゾーン付きの現在時刻を記録する
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
    """
    ユーザーメッセージを受け取り、AI からの返答を生成して返す。

    新規セッションの場合はデータベースにセッションを作成し、
    既存セッションの場合は過去の会話履歴を取得して文脈のある返答を生成する。
    OpenAI API キーが未設定の場合は設定案内メッセージを返す。

    Args:
        message: ユーザーが送信したメッセージ本文
        symbol: 相談対象の通貨ペア（デフォルト: "USDJPY"）
        session_id: 継続するセッションの ID（None の場合は新規セッションを作成）
        tenant_id: テナント ID（マルチテナント分離用）
        user_id: ユーザー ID（ユーザー別の履歴管理用）

    Returns:
        dict: 以下のキーを含む応答辞書
            - session_id: セッション ID（新規作成の場合は新しい ID）
            - symbol: 通貨ペア
            - reply: AI からの返答テキスト
            - messages: セッション内の全メッセージ履歴
            - error: エラーコードまたはメッセージ（エラー時のみ）
    """
    # OpenAI API キーが未設定の場合は早期リターンして設定案内を返す
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
            # 新規セッションを作成する
            # タイトルはメッセージの先頭 60 文字を使用する（UI での識別に使用）
            session = ChatSession(
                tenant_id=tenant_id,
                user_id=user_id,
                symbol=symbol.upper(),
                title=message[:60],
                created_at=datetime.now(timezone.utc),
            )
            db.add(session)
            # flush でセッションを DB に書き込み、ID を取得する（commit は後で行う）
            db.flush()
            session_id = session.id
        else:
            # 既存セッションを検索して継続する
            session = db.get(ChatSession, session_id)
            if not session:
                raise ValueError("セッションが見つかりません")

        # ユーザーメッセージを DB に保存する（コミット前のため他のメッセージと同一トランザクション）
        _save_message(db, session_id, "user", message)
        # 最新 20 件の会話履歴を取得し、文脈として OpenAI に渡す
        history = get_messages(session_id, 20)

        # FX 投資専門アドバイザーとしての役割と制約をシステムプロンプトで定義する
        system = (
            "あなたはFX投資の専門アドバイザーです。"
            f"現在の相談通貨ペア: {symbol}。"
            "日本語で簡潔かつ実用的に回答。具体的な価格は参考値として述べ、"
            "投資助言ではなく教育目的である旨を必要に応じて伝えてください。"
            "リスク管理・テクニカル・ファンダメンタルの観点をバランスよく含めてください。"
        )
        # システムプロンプトを先頭に設定し、過去の会話履歴を続ける
        messages = [{"role": "system", "content": system}]
        # 直近 10 件のみに絞ることでトークン数を抑制し、コストとレスポンス速度を最適化する
        for h in history[-10:]:
            messages.append({"role": h["role"], "content": h["content"]})

        # OpenAI API の同期クライアントを asyncio のスレッドプールで実行する
        client = get_openai_client()
        response = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                # temperature=0.5: 創造性と一貫性のバランスを保つ設定（0=決定論的、1=創造的）
                temperature=0.5,
                # max_tokens=1200: 十分な回答長を確保しつつコストを管理する
                max_tokens=1200,
            )
        )
        # レスポンスから返答テキストを抽出する（None の場合は空文字にフォールバック）
        reply = response.choices[0].message.content or ""
        # AI の返答を DB に保存する
        _save_message(db, session_id, "assistant", reply)
        # ユーザーメッセージと AI 返答を同一トランザクションでコミットする
        db.commit()

        return {
            "session_id": session_id,
            "symbol": symbol.upper(),
            "reply": reply,
            # 全メッセージ履歴を返してフロントエンドが画面を再描画できるようにする
            "messages": get_messages(session_id, 50),
        }
    except Exception as e:
        # エラー時はトランザクションをロールバックしてデータの不整合を防ぐ
        db.rollback()
        return {"session_id": session_id, "reply": f"エラー: {e}", "error": str(e)}
    finally:
        # 正常終了・例外発生に関わらず DB コネクションを必ず返却する
        db.close()
