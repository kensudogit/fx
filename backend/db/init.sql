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
