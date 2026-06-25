-- FX Tool PostgreSQL schema

CREATE TABLE IF NOT EXISTS fx_pairs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL UNIQUE,
    base_currency VARCHAR(3) NOT NULL,
    quote_currency VARCHAR(3) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ohlcv_data (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(18, 6) NOT NULL,
    high NUMERIC(18, 6) NOT NULL,
    low NUMERIC(18, 6) NOT NULL,
    close NUMERIC(18, 6) NOT NULL,
    volume BIGINT DEFAULT 0,
    timeframe VARCHAR(10) NOT NULL DEFAULT '1d',
    UNIQUE(symbol, timestamp, timeframe)
);

CREATE INDEX idx_ohlcv_symbol_time ON ohlcv_data(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS fundamental_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    country VARCHAR(3) NOT NULL,
    title VARCHAR(255) NOT NULL,
    event_date DATE NOT NULL,
    actual_value NUMERIC(18, 4),
    forecast_value NUMERIC(18, 4),
    previous_value NUMERIC(18, 4),
    unit VARCHAR(50),
    impact VARCHAR(10) DEFAULT 'medium',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fundamental_event_date ON fundamental_events(event_date DESC);
CREATE INDEX idx_fundamental_event_type ON fundamental_events(event_type);

INSERT INTO fx_pairs (symbol, base_currency, quote_currency) VALUES
    ('USDJPY', 'USD', 'JPY'),
    ('EURUSD', 'EUR', 'USD'),
    ('GBPUSD', 'GBP', 'USD'),
    ('AUDUSD', 'AUD', 'USD')
ON CONFLICT (symbol) DO NOTHING;

CREATE TABLE IF NOT EXISTS tradingview_signals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    price NUMERIC(18, 6),
    strategy VARCHAR(100),
    message VARCHAR(500),
    source VARCHAR(30) DEFAULT 'tradingview',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_signals_received ON tradingview_signals(received_at DESC);

CREATE TABLE IF NOT EXISTS broker_orders (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(10) NOT NULL,
    units INTEGER NOT NULL,
    order_type VARCHAR(20) DEFAULT 'MARKET',
    status VARCHAR(20) DEFAULT 'PENDING',
    fill_price NUMERIC(18, 6),
    broker VARCHAR(20) DEFAULT 'paper',
    external_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_broker_orders_created ON broker_orders(created_at DESC);

-- SaaS: テナント・ユーザー
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    slug VARCHAR(80) NOT NULL UNIQUE,
    plan VARCHAR(20) NOT NULL DEFAULT 'free',
    stripe_customer_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'owner',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_api_keys (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL DEFAULT 'Default',
    key_prefix VARCHAR(20) NOT NULL,
    key_hash VARCHAR(64) NOT NULL,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON tenant_api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON tenant_api_keys(key_hash);

CREATE TABLE IF NOT EXISTS usage_events (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL DEFAULT 'api_call',
    path VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_tenant_day ON usage_events(tenant_id, created_at DESC);

ALTER TABLE tradingview_signals ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id);
ALTER TABLE broker_orders ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id);
CREATE INDEX IF NOT EXISTS idx_tv_signals_tenant ON tradingview_signals(tenant_id);
CREATE INDEX IF NOT EXISTS idx_broker_orders_tenant ON broker_orders(tenant_id);
