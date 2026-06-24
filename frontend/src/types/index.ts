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
