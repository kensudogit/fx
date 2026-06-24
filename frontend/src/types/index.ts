export interface OHLCV {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TechnicalAnalysis {
  symbol: string;
  timestamps: string[];
  ohlcv: {
    open: (number | null)[];
    high: (number | null)[];
    low: (number | null)[];
    close: (number | null)[];
  };
  indicators: {
    ma: {
      sma_20: (number | null)[];
      sma_50: (number | null)[];
      ema_12: (number | null)[];
      ema_26: (number | null)[];
    };
    bollinger_bands: {
      upper: (number | null)[];
      middle: (number | null)[];
      lower: (number | null)[];
    };
    macd: {
      macd: (number | null)[];
      signal: (number | null)[];
      histogram: (number | null)[];
    };
    rsi: (number | null)[];
    stochastic: {
      k: (number | null)[];
      d: (number | null)[];
    };
    ichimoku: {
      tenkan: (number | null)[];
      kijun: (number | null)[];
      senkou_a: (number | null)[];
      senkou_b: (number | null)[];
      chikou: (number | null)[];
    };
  };
  latest: {
    close: number;
    rsi: number | null;
    macd: number | null;
  };
  source?: string;
}

export interface TradingSignal {
  indicator: string;
  signal: "buy" | "sell";
  value?: number;
  reason: string;
}

export interface FundamentalEvent {
  date: string;
  value: number;
  previous?: number;
  forecast?: number;
  unit?: string;
  title?: string;
}

export interface FundamentalData {
  events: Record<
    string,
    {
      label: string;
      source: string;
      data: FundamentalEvent[];
    }
  >;
  labels: Record<string, string>;
}

export interface CalendarEvent {
  date: string;
  event_type: string;
  title: string;
  country: string;
  impact: string;
}

export interface MLPrediction {
  symbol: string;
  status: string;
  prediction?: number;
  current_price?: number;
  train_r2?: number;
  test_r2?: number;
  model?: string;
  message?: string;
}

export interface NewsArticle {
  title: string;
  url: string;
  published_at: string;
  source: string;
}

export interface AINewsAnalysis {
  symbol: string;
  collected_at?: string;
  articles: NewsArticle[];
  summary: string;
  sentiment: "bullish" | "bearish" | "neutral";
  sentiment_score: number;
  key_topics: string[];
  market_impact: string;
  currency_outlook?: { base: string; quote: string };
}

export interface AIFundamentalAnalysis {
  symbol: string;
  overview: string;
  base_currency_analysis: string;
  quote_currency_analysis: string;
  key_indicators: { name: string; impact: string; comment: string }[];
  upcoming_risks: string[];
  pair_bias: string;
  confidence: number;
}

export interface AITradingDecision {
  symbol: string;
  current_price: number;
  action: "buy" | "sell" | "hold";
  confidence: number;
  entry_price: number;
  take_profit: number;
  stop_loss: number;
  timeframe: string;
  reasoning: string;
  technical_view: string;
  fundamental_view: string;
  news_view: string;
  risk_reward_ratio: number;
  warnings: string[];
}

export interface AIRiskAssessment {
  symbol: string;
  account_balance: number;
  current_price: number;
  risk_level: string;
  risk_score: number;
  position_size_percent: number;
  position_size_usd: number;
  max_loss_percent: number;
  max_loss_usd: number;
  recommended_leverage: number;
  stop_loss_price: number;
  take_profit_price: number;
  risk_reward_ratio: number;
  volatility_assessment: string;
  market_conditions: string;
  recommendations: string[];
  do_not_trade_if: string[];
}

export interface AIFullReport {
  symbol: string;
  news: AINewsAnalysis;
  fundamentals: AIFundamentalAnalysis;
  trading_decision: AITradingDecision;
  risk_management: AIRiskAssessment;
}
