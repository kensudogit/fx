"""
データベース — db/database

このモジュールは FX トレード支援プラットフォームの一部です。

SQLAlchemy を使用した PostgreSQL 接続・ORM モデル定義に加え、
分析結果のキャッシュバックエンド（DynamoDB またはインメモリ）を提供します。

主な責務:
    - SQLAlchemy エンジン・セッションファクトリーの初期化
    - OHLCV・ファンダメンタルイベントの ORM モデル定義
    - DB スキーマ初期化（init.sql の実行）
    - キャッシュクライアントの生成（DynamoDB 優先 → インメモリフォールバック）
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)

# ── SQLAlchemy エンジン・セッションファクトリー ──────────
# pool_pre_ping=True により、使用前に接続の生存確認を行う（ネットワーク断切れ対策）
engine = create_engine(settings.get_database_url(), pool_pre_ping=True)
# autocommit=False: 明示的な commit() が必要（データ整合性を保証）
# autoflush=False: 自動フラッシュを無効化（意図しない SQL 実行を防止）
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    全 ORM モデルの基底クラス。

    SQLAlchemy の DeclarativeBase を継承し、
    全テーブルのメタデータを管理するための共通基底クラスとして機能する。
    """
    pass


class OHLCVRecord(Base):
    """
    OHLCV（始値・高値・安値・終値・出来高）データの ORM モデル。

    テーブル名: ohlcv_data

    Attributes:
        id: 主キー（自動採番）
        symbol: 通貨ペアシンボル（例: "USDJPY"、最大 10 文字）
        timestamp: ローソク足のタイムスタンプ（タイムゾーン付き）
        open: 始値（小数点以下 6 桁の高精度数値）
        high: 高値（小数点以下 6 桁の高精度数値）
        low: 安値（小数点以下 6 桁の高精度数値）
        close: 終値（小数点以下 6 桁の高精度数値）
        volume: 出来高（整数、FX では参考値として扱う）
        timeframe: 足種（"1d" = 日足、"4h" = 4 時間足）
    """
    __tablename__ = "ohlcv_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    # Numeric(18, 6): 整数部 12 桁 + 小数部 6 桁（FX レートの高精度表現に対応）
    open = Column(Numeric(18, 6), nullable=False)
    high = Column(Numeric(18, 6), nullable=False)
    low = Column(Numeric(18, 6), nullable=False)
    close = Column(Numeric(18, 6), nullable=False)
    volume = Column(Integer, default=0)       # FX では出来高が提供されない場合は 0
    timeframe = Column(String(10), default="1d")  # デフォルトは日足


class FundamentalEvent(Base):
    """
    経済指標・ファンダメンタルイベントの ORM モデル。

    テーブル名: fundamental_events

    Attributes:
        id: 主キー（自動採番）
        event_type: イベント種別（例: "interest_rate", "gdp", "employment"）
        country: 国コード（ISO 3166-1 alpha-3、例: "USA", "JPN"）
        title: イベント名称（例: "FOMC 金利決定"）
        event_date: イベント発生日
        actual_value: 実際の発表値（発表前は NULL）
        forecast_value: 市場予想値（Numeric(18, 4) で小数点 4 桁まで格納）
        previous_value: 前回値
        unit: 値の単位（例: "%", "万人"）
        impact: 市場への影響度（"high" / "medium" / "low"）
    """
    __tablename__ = "fundamental_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False)
    country = Column(String(3), nullable=False)    # ISO 3166-1 alpha-3 形式（3 文字）
    title = Column(String(255), nullable=False)
    event_date = Column(Date, nullable=False)
    # 経済指標は小数点 4 桁まで（例: GDP 成長率 2.5000%）
    actual_value = Column(Numeric(18, 4))
    forecast_value = Column(Numeric(18, 4))
    previous_value = Column(Numeric(18, 4))
    unit = Column(String(50))
    impact = Column(String(10), default="medium")  # デフォルト影響度は medium


def get_db():
    """
    FastAPI 依存性注入用のデータベースセッションジェネレーター。

    リクエストごとに新しいセッションを生成し、処理完了後に確実にクローズする。
    FastAPI の Depends() と組み合わせて使用する。

    Yields:
        SQLAlchemy セッションオブジェクト

    Example:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        # 例外発生時も必ずセッションをクローズしてコネクションをプールに返却
        db.close()


def init_database():
    """
    スキーマ初期化（テーブル作成 + シード）

    プロジェクトルートの db/init.sql を読み込み、セミコロン区切りで各 SQL 文を実行する。
    既存テーブルへの重複作成試みは無視し、その他のエラーは警告ログに記録する。

    init.sql が存在しない場合は警告を出力して処理をスキップする。
    アプリケーション起動時（lifespan 関数内）に一度だけ呼び出される。
    """
    # プロジェクト構造: src/db/database.py → ../../../db/init.sql を解決
    init_sql = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"
    if not init_sql.exists():
        logger.warning("init.sql not found")
        return

    sql = init_sql.read_text(encoding="utf-8")
    # セミコロンで各 SQL 文に分割し、空文字を除外する
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                msg = str(e).lower()
                # "already exists" / "duplicate" エラーは冪等性のため無視（再起動時の安全な再実行）
                if "already exists" in msg or "duplicate" in msg:
                    continue
                logger.warning("SQL init statement skipped: %s — %s", stmt[:80], e)


class InMemoryCache:
    """
    プロセス内インメモリ TTL キャッシュ。

    DynamoDB が利用できない環境（ローカル開発等）でのフォールバック実装。
    Python 辞書をバッキングストアとし、TTL（有効期限）によるエントリ管理を行う。
    シングルプロセス内のみ有効なため、複数インスタンス間でキャッシュは共有されない。

    Attributes:
        _store: キャッシュエントリを格納する辞書
                キー: キャッシュキー文字列
                値: {"data": 実データ, "expires_at": Unix タイムスタンプ（秒）}
    """

    def __init__(self):
        """キャッシュストアを空の辞書で初期化する。"""
        self._store: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        """
        キャッシュからエントリを取得する。

        エントリが存在しない場合、または有効期限切れの場合は None を返す。
        有効期限切れのエントリはこのタイミングで削除される（遅延削除）。

        Args:
            key: キャッシュキー文字列

        Returns:
            有効なキャッシュデータ辞書、またはキャッシュミスの場合は None
        """
        entry = self._store.get(key)
        if not entry:
            return None
        if entry["expires_at"] < datetime.utcnow().timestamp():
            # TTL 超過: エントリを削除して None を返す（遅延削除方式）
            del self._store[key]
            return None
        return entry["data"]

    def put(self, key: str, data: dict, ttl_seconds: int = 3600):
        """
        キャッシュにエントリを保存する。

        同一キーの既存エントリは上書きされる。

        Args:
            key: キャッシュキー文字列
            data: 保存するデータ辞書
            ttl_seconds: キャッシュ有効期間（秒）、デフォルト 3600 秒 = 1 時間
        """
        # 現在時刻 + TTL で有効期限 Unix タイムスタンプを計算
        self._store[key] = {
            "data": data,
            "expires_at": datetime.utcnow().timestamp() + ttl_seconds,
        }


class DynamoDBClient:
    """
    AWS DynamoDB を使用したキャッシュクライアント。

    分散環境（複数サーバー・コンテナ）でキャッシュを共有するための実装。
    LocalStack を使用したローカル開発にも対応。
    DynamoDB の TTL 機能を利用してエントリの自動期限切れを実現する。

    Attributes:
        TABLE_NAME: DynamoDB テーブル名（固定値）
        client: boto3 DynamoDB リソースオブジェクト
    """

    TABLE_NAME = "fx_analysis_cache"  # キャッシュ用 DynamoDB テーブル名（固定）

    def __init__(self):
        """
        DynamoDB クライアントを初期化し、テーブルの存在を確認・作成する。

        boto3 の DynamoDB リソースを初期化し、接続設定を適用する。
        ローカル環境では endpoint_url（LocalStack 等）を指定可能。

        Raises:
            RuntimeError: DynamoDB エンドポイントが未設定の場合
        """
        import boto3

        endpoint = settings.dynamodb_endpoint
        if not endpoint:
            raise RuntimeError("DynamoDB endpoint not configured")

        # boto3 接続パラメーターを動的に組み立て
        kwargs = {
            "region_name": settings.aws_region,
        }
        if endpoint.startswith("http"):
            # LocalStack 等のローカル DynamoDB エミュレーター用エンドポイント
            kwargs["endpoint_url"] = endpoint
        if settings.aws_access_key_id:
            # 明示的な認証情報が設定されている場合のみ使用（EC2 インスタンスロール等は除外）
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.resource("dynamodb", **kwargs)
        # テーブルが存在しない場合は自動作成する
        self._ensure_table()

    def _ensure_table(self):
        """
        キャッシュテーブルが存在することを確認し、なければ作成する。

        PAY_PER_REQUEST 課金モードを使用（読み書き容量の事前設定が不要）。
        テーブルが既に存在する場合（ResourceInUseException）は正常として処理する。

        Raises:
            ClientError: ResourceInUseException 以外の DynamoDB エラーが発生した場合
        """
        from botocore.exceptions import ClientError

        try:
            self.client.create_table(
                TableName=self.TABLE_NAME,
                # cache_key をパーティションキー（HASH キー）として使用
                KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
                # オンデマンド課金: トラフィックに応じて自動スケール
                BillingMode="PAY_PER_REQUEST",
            )
            # テーブルが ACTIVE 状態になるまで待機
            self.client.Table(self.TABLE_NAME).wait_until_exists()
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                # テーブル既存以外のエラーは再送出する
                raise

    def get(self, key: str) -> dict | None:
        """
        DynamoDB からキャッシュエントリを取得する。

        Args:
            key: キャッシュキー文字列

        Returns:
            キャッシュデータ辞書（JSON デシリアライズ済み）、またはキャッシュミス時は None
        """
        table = self.client.Table(self.TABLE_NAME)
        response = table.get_item(Key={"cache_key": key})
        item = response.get("Item")
        if item and "data_json" in item:
            # JSON 文字列を Python 辞書にデシリアライズして返す
            return json.loads(item["data_json"])
        return None

    def put(self, key: str, data: dict, ttl_seconds: int = 3600):
        """
        DynamoDB にキャッシュエントリを保存する。

        データは JSON 文字列にシリアライズして格納する。
        ttl フィールドに Unix タイムスタンプを設定することで、
        DynamoDB の TTL 機能による自動削除を有効にする。

        Args:
            key: キャッシュキー文字列
            data: 保存するデータ辞書（JSON シリアライズ可能な形式）
            ttl_seconds: キャッシュ有効期間（秒）、デフォルト 3600 秒 = 1 時間
        """
        table = self.client.Table(self.TABLE_NAME)
        table.put_item(
            Item={
                "cache_key": key,
                "data_json": json.dumps(data),             # データを JSON 文字列としてシリアライズ
                "created_at": datetime.utcnow().isoformat(), # 作成日時（デバッグ・監査用）
                # DynamoDB TTL: 現在の Unix タイムスタンプ + TTL 秒数 = 自動削除時刻
                "ttl": int(datetime.utcnow().timestamp()) + ttl_seconds,
            }
        )


def create_cache_client():
    """
    利用可能なバックエンドに応じてキャッシュクライアントを生成して返す。

    DynamoDB エンドポイントが設定されている場合は DynamoDBClient を優先して使用する。
    DynamoDB が利用できない場合（設定なし・接続失敗）はインメモリキャッシュにフォールバックする。

    Returns:
        DynamoDBClient または InMemoryCache のインスタンス
    """
    if settings.dynamodb_endpoint:
        try:
            return DynamoDBClient()
        except Exception as e:
            # DynamoDB 接続失敗時はインメモリキャッシュにフォールバック（起動を止めない）
            logger.warning("DynamoDB unavailable, using in-memory cache: %s", e)
    return InMemoryCache()


# モジュールロード時にキャッシュクライアントを生成するシングルトン
# 他モジュールは `from src.db.database import dynamodb_client` でこのインスタンスを参照する
dynamodb_client = create_cache_client()
