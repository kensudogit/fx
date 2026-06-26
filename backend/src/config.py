from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_user: str = "fx_user"
    postgres_password: str = "fx_password"
    postgres_db: str = "fx_db"
    database_url: str = ""

    dynamodb_endpoint: str = ""
    aws_region: str = "ap-northeast-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    fred_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"  # practice | live

    tradingview_webhook_secret: str = ""

    autotrade_enabled: bool = True
    autotrade_interval_minutes: int = 15

    jwt_secret: str = "change-me-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 72

    saas_enabled: bool = True
    saas_default_plan: str = "free"  # 新規登録時のプラン（free | pro | enterprise）
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""
    stripe_price_enterprise: str = ""
    app_public_url: str = "http://localhost:3000"

    cors_origins: str = "http://localhost:3000"
    port: int = 8000

    class Config:
        env_file = ".env"
        extra = "ignore"

    def get_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
        else:
            url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
