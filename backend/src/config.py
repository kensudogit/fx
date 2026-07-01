"""
アプリケーション設定 — config

このモジュールは FX トレード支援プラットフォームの一部です。
pydantic_settings を使用して環境変数 / .env ファイルから設定値を読み込み、
アプリケーション全体で共有する Settings シングルトンを提供します。
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    アプリケーション全体の設定クラス。

    環境変数または .env ファイルの値を自動的に読み込む。
    各フィールドにはデフォルト値が設定されており、開発環境ではそのまま動作する。

    Attributes:
        postgres_host: PostgreSQL サーバーのホスト名
        postgres_port: PostgreSQL サーバーのポート番号（デフォルト: 5433）
        postgres_user: PostgreSQL 接続ユーザー名
        postgres_password: PostgreSQL 接続パスワード
        postgres_db: 接続先データベース名
        database_url: DATABASE_URL 環境変数による完全な接続 URL（設定時優先）
        dynamodb_endpoint: DynamoDB（LocalStack 等）のエンドポイント URL
        aws_region: AWS リージョン（デフォルト: ap-northeast-1 = 東京）
        aws_access_key_id: AWS アクセスキー ID
        aws_secret_access_key: AWS シークレットアクセスキー
        fred_api_key: FRED（米連邦準備制度経済データ）API キー
        openai_api_key: OpenAI API キー（AI 分析機能で使用）
        openai_model: 使用する OpenAI モデル名
        oanda_api_token: OANDA ブローカー API トークン
        oanda_account_id: OANDA 口座 ID
        oanda_environment: OANDA 環境（practice=デモ / live=本番）
        tradingview_webhook_secret: TradingView Webhook 検証用シークレット
        autotrade_enabled: 自動売買スケジューラーの有効・無効フラグ
        autotrade_interval_minutes: 自動売買実行間隔（分単位）
        jwt_secret: JWT 署名用シークレットキー（本番では必ず変更する）
        jwt_algorithm: JWT 署名アルゴリズム（HS256 = HMAC-SHA256）
        jwt_expire_hours: JWT トークンの有効期間（時間単位）
        saas_enabled: マルチテナント SaaS モードの有効・無効フラグ
        saas_default_plan: 新規ユーザーのデフォルトプラン名
        stripe_secret_key: Stripe 決済 API シークレットキー
        stripe_webhook_secret: Stripe Webhook 検証用シークレット
        stripe_price_pro: Stripe の Pro プラン価格 ID
        stripe_price_enterprise: Stripe の Enterprise プラン価格 ID
        app_public_url: フロントエンドアプリの公開 URL（Stripe リダイレクト等で使用）
        redis_url: Redis 接続 URL（分散ロック・キャッシュ用）
        finnhub_api_key: Finnhub 金融データ API キー
        analysis_cache_ttl_seconds: ML / インテリジェンス分析結果のキャッシュ有効期間（秒）
        mtf_cache_ttl_seconds: マルチタイムフレーム分析キャッシュの有効期間（秒）
        ml_model_ttl_seconds: ディスク上の学習済み sklearn モデルの有効期間（秒）
        ml_price_backend: 価格予測に使用する ML バックエンド（auto / sklearn / tensorflow / pytorch）
        ml_lstm_lookback: LSTM モデルへの入力系列長（タイムステップ数）
        ml_lstm_epochs: LSTM モデルのエポック数
        ml_lstm_units: LSTM レイヤーのユニット数
        ml_lstm_batch_size: LSTM 学習のバッチサイズ
        signal_context_cache_ttl_seconds: 自動売買シグナル統合コンテキストのキャッシュ有効期間（秒）
        sns_cache_ttl_seconds: SNS センチメント分析キャッシュの有効期間（秒）
        cache_warmup_enabled: 起動時キャッシュウォームアップの有効・無効フラグ
        cache_warmup_symbols: ウォームアップ対象通貨ペア（カンマ区切り文字列）
        cors_origins: CORS 許可オリジン（カンマ区切り文字列）
        port: FastAPI サーバーの待ち受けポート番号
    """

    # ── PostgreSQL 接続設定 ──────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5433          # デフォルト 5433（5432 と競合しないよう Docker Compose で設定）
    postgres_user: str = "fx_user"
    postgres_password: str = "fx_password"
    postgres_db: str = "fx_db"
    database_url: str = ""             # 設定時は個別フィールドより優先（Heroku / Railway 等の DATABASE_URL）

    # ── AWS / DynamoDB 設定 ──────────────────────────────
    dynamodb_endpoint: str = ""        # 空文字の場合はインメモリキャッシュにフォールバック
    aws_region: str = "ap-northeast-1" # 東京リージョン（デフォルト）
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # ── 外部 API キー ────────────────────────────────────
    fred_api_key: str = ""             # 米国経済指標データ取得用
    openai_api_key: str = ""           # AI 分析・ニュース解析に使用
    openai_model: str = "gpt-4o-mini"  # コスト効率の良い軽量モデルをデフォルトに設定

    # ── OANDA ブローカー設定 ─────────────────────────────
    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"  # practice | live

    # ── TradingView Webhook 設定 ─────────────────────────
    tradingview_webhook_secret: str = ""  # Webhook の正当性を検証するためのシークレット

    # ── 自動売買スケジューラー設定 ───────────────────────
    autotrade_enabled: bool = True
    autotrade_interval_minutes: int = 15  # 15 分ごとに市場スキャンを実行（単位: 分）

    # ── JWT 認証設定 ─────────────────────────────────────
    jwt_secret: str = "change-me-in-production-use-long-random-string"  # 本番環境では必ずランダムな長い文字列に変更
    jwt_algorithm: str = "HS256"         # HMAC-SHA256 署名アルゴリズム
    jwt_expire_hours: int = 72           # トークン有効期間: 72 時間 = 3 日間

    # ── SaaS / Stripe 設定 ──────────────────────────────
    saas_enabled: bool = True
    saas_default_plan: str = "free"  # 新規登録時のプラン（free | pro | enterprise）
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""         # Stripe ダッシュボードで発行された Pro プラン価格 ID
    stripe_price_enterprise: str = ""  # Stripe ダッシュボードで発行された Enterprise プラン価格 ID
    app_public_url: str = "http://localhost:3000"  # Stripe 決済完了後のリダイレクト先

    # ── Redis 設定 ───────────────────────────────────────
    redis_url: str = ""  # 空文字の場合はプロセス内ロックにフォールバック

    # ── Finnhub 設定 ─────────────────────────────────────
    finnhub_api_key: str = ""

    # ── ML / キャッシュ TTL 設定 ─────────────────────────
    analysis_cache_ttl_seconds: int = 900  # ML / インテリジェンス結果キャッシュ（15分 = 900秒）
    mtf_cache_ttl_seconds: int = 900       # マルチタイムフレーム分析キャッシュ（15分）
    ml_model_ttl_seconds: int = 3600       # ディスク上の sklearn モデル有効期間（1時間 = 3600秒）
    ml_price_backend: str = "auto"         # auto | sklearn | tensorflow | pytorch
    ml_lstm_lookback: int = 20             # LSTM 入力系列長（過去 20 タイムステップを入力として使用）
    ml_lstm_epochs: int = 25              # LSTM 学習エポック数（過学習防止のため小さめに設定）
    ml_lstm_units: int = 32               # LSTM 隠れ層のユニット数（軽量化のため小さめ）
    ml_lstm_batch_size: int = 16          # LSTM 学習バッチサイズ
    signal_context_cache_ttl_seconds: int = 300  # 自動売買シグナル統合（5分 = 300秒）
    sns_cache_ttl_seconds: int = 600       # SNS センチメント分析キャッシュ（10分 = 600秒）
    cache_warmup_enabled: bool = True      # True にすると起動時に主要通貨ペアを事前計算
    cache_warmup_symbols: str = "USDJPY,EURUSD,GBPUSD"  # ウォームアップ対象通貨ペア

    # ── サーバー設定 ─────────────────────────────────────
    cors_origins: str = "http://localhost:3000"  # 開発時のフロントエンドオリジン
    port: int = 8000                              # FastAPI 待ち受けポート

    class Config:
        """pydantic_settings の動作設定。"""
        env_file = ".env"    # .env ファイルから環境変数を自動読み込み
        extra = "ignore"     # 定義外の環境変数は無視する（エラーにしない）

    def get_database_url(self) -> str:
        """
        SQLAlchemy 接続用の完全な PostgreSQL URL を返す。

        DATABASE_URL 環境変数が設定されている場合はそれを使用し、
        未設定の場合は個別フィールド（postgres_host / port / user / password / db）から URL を組み立てる。
        psycopg3 ドライバー互換のスキーム（postgresql+psycopg://）に正規化して返す。

        Returns:
            SQLAlchemy が受け付ける形式の PostgreSQL 接続 URL 文字列。
        """
        if self.database_url:
            # DATABASE_URL 環境変数が設定されている場合はそちらを優先
            url = self.database_url
        else:
            # 個別フィールドから URL を組み立てる
            url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        # Heroku / Railway 等が出力する postgres:// スキームを psycopg3 互換に変換
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            # psycopg2 スキームを psycopg3 スキームに変換
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def get_cors_origins(self) -> list[str]:
        """
        CORS 許可オリジンのリストを返す。

        cors_origins フィールドはカンマ区切りの文字列として保持されており、
        このメソッドで分割・トリミングしてリスト形式に変換する。

        Returns:
            CORS 許可オリジン文字列のリスト（空文字は除外済み）。
        """
        # カンマで分割し、前後の空白を除去してから空文字を除外する
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# アプリケーション全体で共有するシングルトンインスタンス
# 他モジュールは `from src.config import settings` でこのインスタンスを参照する
settings = Settings()
