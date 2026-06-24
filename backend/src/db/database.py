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

engine = create_engine(settings.get_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class OHLCVRecord(Base):
    __tablename__ = "ohlcv_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Numeric(18, 6), nullable=False)
    high = Column(Numeric(18, 6), nullable=False)
    low = Column(Numeric(18, 6), nullable=False)
    close = Column(Numeric(18, 6), nullable=False)
    volume = Column(Integer, default=0)
    timeframe = Column(String(10), default="1d")


class FundamentalEvent(Base):
    __tablename__ = "fundamental_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False)
    country = Column(String(3), nullable=False)
    title = Column(String(255), nullable=False)
    event_date = Column(Date, nullable=False)
    actual_value = Column(Numeric(18, 4))
    forecast_value = Column(Numeric(18, 4))
    previous_value = Column(Numeric(18, 4))
    unit = Column(String(50))
    impact = Column(String(10), default="medium")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """スキーマ初期化（テーブル作成 + シード）"""
    init_sql = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"
    if not init_sql.exists():
        logger.warning("init.sql not found")
        return

    sql = init_sql.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                    logger.debug("SQL skip: %s", e)


class InMemoryCache:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry["expires_at"] < datetime.utcnow().timestamp():
            del self._store[key]
            return None
        return entry["data"]

    def put(self, key: str, data: dict, ttl_seconds: int = 3600):
        self._store[key] = {
            "data": data,
            "expires_at": datetime.utcnow().timestamp() + ttl_seconds,
        }


class DynamoDBClient:
    TABLE_NAME = "fx_analysis_cache"

    def __init__(self):
        import boto3

        endpoint = settings.dynamodb_endpoint
        if not endpoint:
            raise RuntimeError("DynamoDB endpoint not configured")

        kwargs = {
            "region_name": settings.aws_region,
        }
        if endpoint.startswith("http"):
            kwargs["endpoint_url"] = endpoint
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self.client = boto3.resource("dynamodb", **kwargs)
        self._ensure_table()

    def _ensure_table(self):
        from botocore.exceptions import ClientError

        try:
            self.client.create_table(
                TableName=self.TABLE_NAME,
                KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            self.client.Table(self.TABLE_NAME).wait_until_exists()
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                raise

    def get(self, key: str) -> dict | None:
        table = self.client.Table(self.TABLE_NAME)
        response = table.get_item(Key={"cache_key": key})
        item = response.get("Item")
        if item and "data_json" in item:
            return json.loads(item["data_json"])
        return None

    def put(self, key: str, data: dict, ttl_seconds: int = 3600):
        table = self.client.Table(self.TABLE_NAME)
        table.put_item(
            Item={
                "cache_key": key,
                "data_json": json.dumps(data),
                "created_at": datetime.utcnow().isoformat(),
                "ttl": int(datetime.utcnow().timestamp()) + ttl_seconds,
            }
        )


def create_cache_client():
    if settings.dynamodb_endpoint:
        try:
            return DynamoDBClient()
        except Exception as e:
            logger.warning("DynamoDB unavailable, using in-memory cache: %s", e)
    return InMemoryCache()


dynamodb_client = create_cache_client()
