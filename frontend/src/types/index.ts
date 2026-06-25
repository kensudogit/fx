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

export interface MultiTimeframeTrend {
  trend: string;
  label: string;
  close: number;
  sma_20: number;
  sma_50: number;
  rsi: number | null;
  signal_bias: string;
  bars: number;
  timeframe: string;
  source: string;
}

export interface MultiTimeframeAnalysis {
  symbol: string;
  alignment: string;
  alignment_label: string;
  timeframes: Record<string, MultiTimeframeTrend>;
}

export interface SignalBacktest {
  symbol: string;
  source?: string;
  total_trades: number;
  win_rate: number;
  avg_return_pct: number;
  buy_trades: number;
  sell_trades: number;
  period_bars?: number;
  message?: string;
}

export interface PositionSizeResult {
  symbol: string;
  price: number;
  account_balance: number;
  risk_percent: number;
  risk_amount_usd: number;
  stop_pips: number;
  pip_size: number;
  pip_value_per_lot_usd: number;
  recommended_lots: number;
  position_notional_usd: number;
  max_loss_usd: number;
  atr_based_stop: boolean;
  suggested_take_profit_pips: number;
}

export interface EventAlert {
  date: string;
  event_type: string;
  title: string;
  country: string;
  impact: string;
  hours_until: number;
}

export interface TradingViewSignal {
  id: number;
  symbol: string;
  action: string;
  price: number | null;
  strategy: string | null;
  message: string | null;
  source: string;
  received_at: string | null;
}

export interface MLNewsAnalysis {
  method: string;
  sentiment: "bullish" | "bearish" | "neutral";
  sentiment_score: number;
  bullish_hits: number;
  bearish_hits: number;
  key_topics: string[];
  summary: string;
}

export interface NewsAnalysisResult {
  symbol: string;
  articles: NewsArticle[];
  ml: MLNewsAnalysis;
  openai: Pick<
    AINewsAnalysis,
    "summary" | "sentiment" | "sentiment_score" | "key_topics" | "market_impact"
  > | null;
  openai_error?: string;
}

export interface BacktraderResult {
  status: string;
  engine?: string;
  symbol?: string;
  source?: string;
  initial_cash?: number;
  final_value?: number;
  total_return_pct?: number;
  bars?: number;
  strategy?: string;
  message?: string;
}

export interface OandaStatus {
  configured: boolean;
  mode: string;
  balance: number;
  currency: string;
  message?: string;
  unrealized_pl?: number;
  open_trade_count?: number;
}

export interface BrokerOrder {
  id: number;
  symbol: string;
  side: string;
  units: number;
  status: string;
  fill_price: number | null;
  broker: string;
  external_id: string | null;
  created_at: string | null;
}

export interface DashboardData {
  symbol: string;
  price: number;
  source: string;
  signals: TradingSignal[];
  multi_timeframe: MultiTimeframeAnalysis;
  news_ml: MLNewsAnalysis & { article_count: number };
  openai_configured: boolean;
  backtest_simple: SignalBacktest;
  backtest_backtrader: BacktraderResult;
  tradingview_signals: TradingViewSignal[];
  oanda: OandaStatus;
  recent_orders: BrokerOrder[];
  stack: { api: string; frontend: string; note: string };
}

export interface TrendPrediction {
  symbol: string;
  source: string;
  current_price: number;
  trend: "bullish" | "bearish" | "neutral";
  trend_label: string;
  confidence: number;
  horizon_days: number;
  rule_based: { trend: string; reasons: string[] };
  ml: {
    status: string;
    trend?: string;
    confidence?: number;
    horizon_days?: number;
    test_accuracy?: number;
    model?: string;
  };
  multi_timeframe: { alignment: string; alignment_label: string };
}

export interface VolatilityPrediction {
  symbol: string;
  source: string;
  current_price: number;
  forecast_days: number;
  current: { atr: number; atr_percent: number; daily_volatility: number };
  forecast: {
    atr: number;
    atr_percent: number;
    daily_volatility_pct: number;
    regime: string;
    regime_label: string;
    vol_trend: string;
    vol_trend_label: string;
    change_vs_current_pct: number;
  };
  ml: { status: string; model: string; predicted_atr: number };
  interpretation: string;
}

export interface SNSPost {
  title: string;
  url: string;
  subreddit: string;
  score: number;
  num_comments: number;
  published_at: string;
  source: string;
}

export interface SNSAnalysis {
  symbol: string;
  collected_at: string;
  platform: string;
  post_count: number;
  posts: SNSPost[];
  sentiment: MLNewsAnalysis;
  engagement: string;
  total_score: number;
  total_comments: number;
  subreddits: Record<string, number>;
  summary: string;
}

export interface EconomicIndicator {
  key: string;
  name: string;
  source: string;
  latest_date?: string;
  value?: number;
  previous?: number;
  forecast?: number;
  unit?: string;
  impact: string;
  pair_direction: string;
  comment: string;
}

export interface EconomicAnalysis {
  symbol: string;
  base_currency: string;
  quote_currency: string;
  pair_bias: "bullish" | "bearish" | "neutral";
  pair_bias_label: string;
  score: number;
  indicators: EconomicIndicator[];
  upcoming_events: CalendarEvent[];
  high_impact_alerts: EventAlert[];
  overview: string;
}

export interface IntelligenceReport {
  symbol: string;
  composite_score: number;
  outlook: "bullish" | "bearish" | "neutral";
  outlook_label: string;
  trend: TrendPrediction;
  news: NewsAnalysisResult;
  sns: SNSAnalysis;
  economic: EconomicAnalysis;
  volatility: VolatilityPrediction;
}
