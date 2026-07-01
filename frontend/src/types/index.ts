/**
 * @file types/index.ts
 * @description フロントエンド全体で使用する TypeScript 型定義。
 *
 * バックエンド FastAPI の Pydantic モデルと対応しており、
 * API レスポンスの型安全を確保するために使用される。
 * 各インターフェースのフィールドには日本語で意味と用途を記述している。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

/**
 * OHLCV（始値・高値・安値・終値・出来高）の単一バーデータ。
 *
 * チャート描画やテクニカル分析の基本データ単位。
 */
export interface OHLCV {
  /** バーの日時（ISO 8601 形式、例: `"2024-01-15T00:00:00Z"`） */
  timestamp: string;
  /** 始値（Open） */
  open: number;
  /** 高値（High） */
  high: number;
  /** 安値（Low） */
  low: number;
  /** 終値（Close） */
  close: number;
  /** 出来高（Volume）。FX では通常ティック数や名目出来高 */
  volume: number;
}

/**
 * テクニカル分析データの総合レスポンス型。
 *
 * `/api/technical/{symbol}` エンドポイントのレスポンスに対応する。
 * OHLCV データと各種インジケーターの時系列配列が含まれる。
 */
export interface TechnicalAnalysis {
  /** 通貨ペアシンボル（例: `"USDJPY"`） */
  symbol: string;
  /** 各インデックスに対応する日時の配列 */
  timestamps: string[];
  /** OHLCV データ（各配列の長さは `timestamps` と同じ） */
  ohlcv: {
    /** 始値の配列 */
    open: (number | null)[];
    /** 高値の配列 */
    high: (number | null)[];
    /** 安値の配列 */
    low: (number | null)[];
    /** 終値の配列 */
    close: (number | null)[];
  };
  /** テクニカルインジケーターの計算結果 */
  indicators: {
    /** 移動平均線（SMA・EMA） */
    ma: {
      /** 20 期間単純移動平均（SMA20） */
      sma_20: (number | null)[];
      /** 50 期間単純移動平均（SMA50） */
      sma_50: (number | null)[];
      /** 12 期間指数移動平均（EMA12）— MACD 計算に使用 */
      ema_12: (number | null)[];
      /** 26 期間指数移動平均（EMA26）— MACD 計算に使用 */
      ema_26: (number | null)[];
    };
    /** ボリンジャーバンド（標準偏差 2 倍） */
    bollinger_bands: {
      /** アッパーバンド */
      upper: (number | null)[];
      /** ミドルバンド（SMA20 と同値） */
      middle: (number | null)[];
      /** ロワーバンド */
      lower: (number | null)[];
    };
    /** MACD（Moving Average Convergence Divergence）*/
    macd: {
      /** MACD ライン（EMA12 - EMA26） */
      macd: (number | null)[];
      /** シグナルライン（MACD の EMA9） */
      signal: (number | null)[];
      /** ヒストグラム（MACD - シグナル） */
      histogram: (number | null)[];
    };
    /** RSI（Relative Strength Index）— 0〜100 の値、70 超が買われすぎ、30 未満が売られすぎ */
    rsi: (number | null)[];
    /** ストキャスティクス */
    stochastic: {
      /** %K ライン（当日の位置） */
      k: (number | null)[];
      /** %D ライン（%K の移動平均） */
      d: (number | null)[];
    };
    /** 一目均衡表 */
    ichimoku: {
      /** 転換線（9 期間高値+安値の平均÷2） */
      tenkan: (number | null)[];
      /** 基準線（26 期間高値+安値の平均÷2） */
      kijun: (number | null)[];
      /** 先行スパン A（転換線+基準線の平均、26 期間先行） */
      senkou_a: (number | null)[];
      /** 先行スパン B（52 期間高値+安値の平均、26 期間先行） */
      senkou_b: (number | null)[];
      /** 遅行スパン（当日終値を 26 期間遡らせたもの） */
      chikou: (number | null)[];
    };
  };
  /** 最新バーのサマリー値（ウィジェット表示用） */
  latest: {
    /** 最新終値 */
    close: number;
    /** 最新 RSI 値 */
    rsi: number | null;
    /** 最新 MACD 値 */
    macd: number | null;
  };
  /** データの取得元識別子（例: `"database"` / `"yahoo_finance"`） */
  source?: string;
}

/**
 * 単一のトレードシグナル。
 *
 * テクニカルインジケーターから生成された売買推奨を表す。
 */
export interface TradingSignal {
  /** シグナルを生成したインジケーター名（例: `"RSI"` / `"MACD"`） */
  indicator: string;
  /** シグナルの方向（`"buy"` = 買い推奨、`"sell"` = 売り推奨） */
  signal: "buy" | "sell";
  /** インジケーターの現在値（あれば） */
  value?: number;
  /** シグナル生成の根拠を説明するテキスト */
  reason: string;
}

/**
 * ファンダメンタルズイベントの単一データポイント。
 *
 * 経済指標の特定日時の発表値を表す。
 */
export interface FundamentalEvent {
  /** 発表日時（ISO 8601 形式） */
  date: string;
  /** 発表値 */
  value: number;
  /** 前回値 */
  previous?: number;
  /** 事前予測値 */
  forecast?: number;
  /** 値の単位（例: `"%"` / `"万人"`） */
  unit?: string;
  /** イベントの表示タイトル */
  title?: string;
}

/**
 * ファンダメンタルズデータの総合レスポンス型。
 *
 * `/api/fundamental` エンドポイントのレスポンスに対応する。
 * イベント種別ごとに時系列データが格納される。
 */
export interface FundamentalData {
  /**
   * イベント種別をキーとしたデータマップ。
   * キー例: `"us_gdp"` / `"us_cpi"` / `"us_nfp"`
   */
  events: Record<
    string,
    {
      /** イベントの表示ラベル */
      label: string;
      /** データソース名（例: `"FRED"` / `"BLS"`） */
      source: string;
      /** 時系列データポイントの配列 */
      data: FundamentalEvent[];
    }
  >;
  /** イベント種別キーから日本語ラベルへのマッピング */
  labels: Record<string, string>;
}

/**
 * 経済カレンダーの単一イベント。
 *
 * 将来の経済指標発表予定を表す。
 */
export interface CalendarEvent {
  /** 発表予定日時（ISO 8601 形式） */
  date: string;
  /** イベント種別識別子（例: `"us_nfp"`) */
  event_type: string;
  /** イベントの表示タイトル */
  title: string;
  /** 発表国コード（例: `"US"` / `"JP"`） */
  country: string;
  /** 市場への影響度（`"high"` / `"medium"` / `"low"`） */
  impact: string;
}

/**
 * 機械学習モデルによる価格予測結果。
 *
 * `/api/ml/predict/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface MLPrediction {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 予測ステータス（`"success"` / `"error"` など） */
  status: string;
  /** 予測した翌日終値 */
  prediction?: number;
  /** 予測時点の現在価格 */
  current_price?: number;
  /** 学習データに対する R² スコア（-∞〜1、1 が完全一致） */
  train_r2?: number;
  /** テストデータに対する R² スコア */
  test_r2?: number;
  /** 使用したモデル名（例: `"RandomForest"`） */
  model?: string;
  /** エラーや警告メッセージ（失敗時） */
  message?: string;
}

/**
 * ニュース記事の基本情報。
 *
 * AI ニュース分析や SNS 分析で収集した記事のメタデータ。
 */
export interface NewsArticle {
  /** 記事タイトル */
  title: string;
  /** 記事の URL */
  url: string;
  /** 公開日時（ISO 8601 形式） */
  published_at: string;
  /** 情報源（メディア名） */
  source: string;
}

/**
 * AI（OpenAI GPT）によるニュース分析結果。
 *
 * `/api/ai/news/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface AINewsAnalysis {
  /** 分析対象の通貨ペアシンボル */
  symbol: string;
  /** データ収集日時 */
  collected_at?: string;
  /** 収集したニュース記事の配列 */
  articles: NewsArticle[];
  /** AI による総合的なニュースサマリー */
  summary: string;
  /** センチメント方向（`"bullish"` = 強気 / `"bearish"` = 弱気 / `"neutral"` = 中立） */
  sentiment: "bullish" | "bearish" | "neutral";
  /** センチメントスコア（-1〜+1、正値が強気） */
  sentiment_score: number;
  /** ニュースの主要トピックのリスト */
  key_topics: string[];
  /** 市場への影響評価テキスト */
  market_impact: string;
  /** 通貨ペアの見通し（基軸通貨・決済通貨） */
  currency_outlook?: { base: string; quote: string };
}

/**
 * AI によるファンダメンタルズ分析結果。
 *
 * `/api/ai/fundamental-analysis/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface AIFundamentalAnalysis {
  /** 通貨ペアシンボル */
  symbol: string;
  /** ファンダメンタルズの全体的な概要 */
  overview: string;
  /** 基軸通貨（例: USD）の分析テキスト */
  base_currency_analysis: string;
  /** 決済通貨（例: JPY）の分析テキスト */
  quote_currency_analysis: string;
  /** 主要経済指標とその影響のリスト */
  key_indicators: { name: string; impact: string; comment: string }[];
  /** 今後注意すべきリスク要因のリスト */
  upcoming_risks: string[];
  /** 通貨ペアのバイアス（方向感）テキスト */
  pair_bias: string;
  /** 分析の確信度（0〜1） */
  confidence: number;
}

/**
 * AI によるトレード判断（エントリー推奨・価格目標・リスクリワード）。
 *
 * `/api/ai/trading-decision/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface AITradingDecision {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 判断時点の現在価格 */
  current_price: number;
  /** 推奨アクション（`"buy"` / `"sell"` / `"hold"`） */
  action: "buy" | "sell" | "hold";
  /** 推奨の確信度（0〜1） */
  confidence: number;
  /** 推奨エントリー価格 */
  entry_price: number;
  /** 利確目標価格（Take Profit） */
  take_profit: number;
  /** 損切り価格（Stop Loss） */
  stop_loss: number;
  /** 推奨保有期間（例: `"1-3 days"` / `"intraday"`） */
  timeframe: string;
  /** 判断根拠の詳細テキスト */
  reasoning: string;
  /** テクニカル分析の見解 */
  technical_view: string;
  /** ファンダメンタルズの見解 */
  fundamental_view: string;
  /** ニュースに基づく見解 */
  news_view: string;
  /** リスクリワード比（利確幅 ÷ 損切り幅） */
  risk_reward_ratio: number;
  /** 注意事項・警告リスト */
  warnings: string[];
}

/**
 * AI によるリスク評価（ポジションサイズ計算・最大損失額推定）。
 *
 * `/api/ai/risk/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface AIRiskAssessment {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 評価に使用した口座残高（USD） */
  account_balance: number;
  /** 評価時点の現在価格 */
  current_price: number;
  /** リスクレベル（例: `"low"` / `"medium"` / `"high"`） */
  risk_level: string;
  /** リスクスコア（0〜100） */
  risk_score: number;
  /** 推奨ポジションサイズ（口座残高に対する割合 %） */
  position_size_percent: number;
  /** 推奨ポジションサイズ（USD） */
  position_size_usd: number;
  /** 最大損失割合（%） */
  max_loss_percent: number;
  /** 最大損失額（USD） */
  max_loss_usd: number;
  /** 推奨レバレッジ倍率 */
  recommended_leverage: number;
  /** 推奨損切り価格 */
  stop_loss_price: number;
  /** 推奨利確価格 */
  take_profit_price: number;
  /** リスクリワード比 */
  risk_reward_ratio: number;
  /** ボラティリティ評価テキスト */
  volatility_assessment: string;
  /** 市場環境の評価テキスト */
  market_conditions: string;
  /** 具体的な推奨アクションのリスト */
  recommendations: string[];
  /** この条件下ではトレードしてはいけない注意事項リスト */
  do_not_trade_if: string[];
}

/**
 * AI 総合レポート（ニュース・ファンダメンタルズ・トレード判断・リスク管理の統合）。
 *
 * `/api/ai/report/{symbol}` エンドポイントのレスポンスに対応する。
 * 1 リクエストで完全な分析レポートが返される（処理時間が長い）。
 */
export interface AIFullReport {
  /** 通貨ペアシンボル */
  symbol: string;
  /** AI ニュース分析 */
  news: AINewsAnalysis;
  /** AI ファンダメンタルズ分析 */
  fundamentals: AIFundamentalAnalysis;
  /** AI トレード判断 */
  trading_decision: AITradingDecision;
  /** AI リスク評価 */
  risk_management: AIRiskAssessment;
}

/**
 * 単一タイムフレームのトレンド情報。
 *
 * {@link MultiTimeframeAnalysis} の `timeframes` マップの値型。
 */
export interface MultiTimeframeTrend {
  /** トレンド方向（`"bullish"` / `"bearish"` / `"neutral"`） */
  trend: string;
  /** トレンドの日本語ラベル */
  label: string;
  /** 当該タイムフレームの最新終値 */
  close: number;
  /** SMA20 の値 */
  sma_20: number;
  /** SMA50 の値 */
  sma_50: number;
  /** RSI の値 */
  rsi: number | null;
  /** シグナルのバイアス（`"buy"` / `"sell"` / `"neutral"`） */
  signal_bias: string;
  /** 分析に使用したバー数 */
  bars: number;
  /** このデータのタイムフレーム識別子（例: `"1H"` / `"4H"` / `"1D"`） */
  timeframe: string;
  /** データソース */
  source: string;
}

/**
 * マルチタイムフレーム分析の総合結果。
 *
 * `/api/technical/{symbol}/multi-timeframe` エンドポイントのレスポンスに対応する。
 * 複数の時間軸におけるトレンドの整合性を確認するために使用する。
 */
export interface MultiTimeframeAnalysis {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 全タイムフレームのトレンド整合性評価（`"aligned_bullish"` など） */
  alignment: string;
  /** 整合性評価の日本語ラベル */
  alignment_label: string;
  /** タイムフレーム識別子をキーとしたトレンドデータのマップ */
  timeframes: Record<string, MultiTimeframeTrend>;
}

/**
 * シグナルバックテスト（ルールベース信号の過去成績）の結果。
 *
 * `/api/technical/{symbol}/backtest` エンドポイントのレスポンスに対応する。
 */
export interface SignalBacktest {
  /** 通貨ペアシンボル */
  symbol: string;
  /** データソース */
  source?: string;
  /** バックテスト期間中の総トレード数 */
  total_trades: number;
  /** 勝率（0〜1、例: `0.65` = 65%） */
  win_rate: number;
  /** 平均リターン（%） */
  avg_return_pct: number;
  /** 買いシグナルによるトレード数 */
  buy_trades: number;
  /** 売りシグナルによるトレード数 */
  sell_trades: number;
  /** バックテストに使用したバー数 */
  period_bars?: number;
  /** エラーや情報メッセージ */
  message?: string;
}

/**
 * ポジションサイズ計算結果。
 *
 * `/api/position-size/{symbol}` エンドポイントのレスポンスに対応する。
 * ATR ベースのリスク管理計算が含まれる。
 */
export interface PositionSizeResult {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 現在の市場価格 */
  price: number;
  /** 計算に使用した口座残高（USD） */
  account_balance: number;
  /** リスク率（%、例: `1` = 口座残高の 1% をリスクにさらす） */
  risk_percent: number;
  /** リスク金額（USD）= `account_balance × risk_percent / 100` */
  risk_amount_usd: number;
  /** 損切り幅（pips） */
  stop_pips: number;
  /** 1 pip の値（通貨ペアの最小変動単位） */
  pip_size: number;
  /** 1 ロットあたりの 1 pip 価値（USD） */
  pip_value_per_lot_usd: number;
  /** 推奨ロット数 */
  recommended_lots: number;
  /** ポジションの想定元本（USD） */
  position_notional_usd: number;
  /** 損切りに達した場合の最大損失額（USD） */
  max_loss_usd: number;
  /** ATR ベースの損切り幅を使用したかどうか */
  atr_based_stop: boolean;
  /** 推奨利確幅（pips） */
  suggested_take_profit_pips: number;
}

/**
 * 高インパクト経済イベントアラート。
 *
 * 発表が近づいている経済指標のアラート情報を表す。
 */
export interface EventAlert {
  /** 発表日時（ISO 8601 形式） */
  date: string;
  /** イベント種別識別子 */
  event_type: string;
  /** イベントの表示タイトル */
  title: string;
  /** 発表国コード */
  country: string;
  /** 市場への影響度（`"high"` / `"medium"` / `"low"`） */
  impact: string;
  /** 発表まであと何時間か */
  hours_until: number;
}

/**
 * TradingView Webhook 経由で受信したシグナル。
 *
 * TradingView の Pine Script アラートが Webhook で送信されたデータ。
 */
export interface TradingViewSignal {
  /** シグナルのデータベース ID */
  id: number;
  /** 通貨ペアシンボル */
  symbol: string;
  /** アクション（例: `"buy"` / `"sell"` / `"close"`） */
  action: string;
  /** シグナル生成時の価格 */
  price: number | null;
  /** 使用した戦略名 */
  strategy: string | null;
  /** アラートメッセージ本文 */
  message: string | null;
  /** シグナルのソース（例: `"tradingview"`） */
  source: string;
  /** シグナル受信日時 */
  received_at: string | null;
}

/**
 * ML（機械学習）ベースのニュースセンチメント分析結果。
 *
 * キーワードマッチングや TF-IDF などの ML 手法で算出されたセンチメント。
 */
export interface MLNewsAnalysis {
  /** 使用した分析手法名（例: `"keyword_match"` / `"tfidf"`） */
  method: string;
  /** センチメント方向 */
  sentiment: "bullish" | "bearish" | "neutral";
  /** センチメントスコア（-1〜+1） */
  sentiment_score: number;
  /** 強気キーワードのヒット数 */
  bullish_hits: number;
  /** 弱気キーワードのヒット数 */
  bearish_hits: number;
  /** 検出された主要トピックのリスト */
  key_topics: string[];
  /** ML 分析による要約テキスト */
  summary: string;
}

/**
 * ニュース分析の複合結果（ML + OpenAI）。
 *
 * `/api/news/analysis/{symbol}` および `/api/analysis/news/{symbol}` の
 * レスポンスに対応する。ML とオプションの OpenAI 分析の両方が含まれる。
 */
export interface NewsAnalysisResult {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 収集したニュース記事の配列 */
  articles: NewsArticle[];
  /** ML（キーワードマッチ等）によるセンチメント分析結果 */
  ml: MLNewsAnalysis;
  /**
   * OpenAI GPT によるセンチメント分析結果。
   * OpenAI API キーが未設定の場合は `null`。
   */
  openai: Pick<
    AINewsAnalysis,
    "summary" | "sentiment" | "sentiment_score" | "key_topics" | "market_impact"
  > | null;
  /** OpenAI 分析でエラーが発生した場合のエラーメッセージ */
  openai_error?: string;
}

/**
 * Backtrader エンジンによるバックテスト結果。
 *
 * `/api/backtest/backtrader/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface BacktraderResult {
  /** 実行ステータス（`"success"` / `"error"` など） */
  status: string;
  /** 使用したバックテストエンジン名 */
  engine?: string;
  /** 通貨ペアシンボル */
  symbol?: string;
  /** データソース */
  source?: string;
  /** 初期資金（USD） */
  initial_cash?: number;
  /** 最終資産評価額（USD） */
  final_value?: number;
  /** 総リターン（%） */
  total_return_pct?: number;
  /** 使用したバー数 */
  bars?: number;
  /** 使用した戦略名 */
  strategy?: string;
  /** エラーや情報メッセージ */
  message?: string;
}

/**
 * OANDA ブローカーの接続状態・口座サマリー。
 *
 * `/api/oanda/status` エンドポイントのレスポンスに対応する。
 */
export interface OandaStatus {
  /** OANDA API が正しく設定されているかどうか */
  configured: boolean;
  /** 取引モード（`"practice"` / `"live"`） */
  mode: string;
  /** 口座残高 */
  balance: number;
  /** 口座の通貨（例: `"USD"`） */
  currency: string;
  /** 接続状態や設定に関するメッセージ */
  message?: string;
  /** 未実現損益 */
  unrealized_pl?: number;
  /** 現在の未決済ポジション数 */
  open_trade_count?: number;
}

/**
 * ブローカーへの注文情報。
 *
 * OANDA などのブローカーに送信した注文のレコード。
 */
export interface BrokerOrder {
  /** データベース内の注文 ID */
  id: number;
  /** 通貨ペアシンボル */
  symbol: string;
  /** 売買方向（`"buy"` / `"sell"`） */
  side: string;
  /** 取引単位（OANDA の units）*/
  units: number;
  /** 注文ステータス（`"filled"` / `"pending"` / `"cancelled"` など） */
  status: string;
  /** 約定価格（約定前は `null`） */
  fill_price: number | null;
  /** ブローカー名（例: `"oanda"`） */
  broker: string;
  /** ブローカー側の注文 ID */
  external_id: string | null;
  /** 注文作成日時 */
  created_at: string | null;
}

/**
 * ダッシュボード用の統合データ。
 *
 * `/api/dashboard` エンドポイントのレスポンスに対応する。
 * 1 リクエストでダッシュボード表示に必要なすべてのデータが取得できる。
 */
export interface DashboardData {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 現在の市場価格 */
  price: number;
  /** データソース識別子 */
  source: string;
  /** テクニカルシグナルの配列 */
  signals: TradingSignal[];
  /** マルチタイムフレーム分析 */
  multi_timeframe: MultiTimeframeAnalysis;
  /** ML ニュースセンチメント（記事数付き） */
  news_ml: MLNewsAnalysis & { article_count: number };
  /** OpenAI が設定されているかどうか */
  openai_configured: boolean;
  /** シンプルシグナルバックテスト */
  backtest_simple: SignalBacktest;
  /** Backtrader バックテスト */
  backtest_backtrader: BacktraderResult;
  /** TradingView から受信したシグナル */
  tradingview_signals: TradingViewSignal[];
  /** OANDA 口座の状態 */
  oanda: OandaStatus;
  /** 直近の注文履歴 */
  recent_orders: BrokerOrder[];
  /** API・フロントエンドのバージョン情報 */
  stack: { api: string; frontend: string; note: string };
}

/**
 * トレンド予測の総合結果（ルールベース + ML）。
 *
 * `/api/analysis/trend/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface TrendPrediction {
  /** 通貨ペアシンボル */
  symbol: string;
  /** データソース */
  source: string;
  /** 現在価格 */
  current_price: number;
  /** 総合トレンド方向 */
  trend: "bullish" | "bearish" | "neutral";
  /** トレンドの日本語ラベル */
  trend_label: string;
  /** 総合確信度（0〜1） */
  confidence: number;
  /** 予測ホライゾン（日数） */
  horizon_days: number;
  /** ルールベース判断（移動平均・RSI 等による） */
  rule_based: { trend: string; reasons: string[] };
  /** ML モデルによる予測 */
  ml: {
    /** 予測ステータス */
    status: string;
    /** ML が予測したトレンド方向 */
    trend?: string;
    /** ML モデルの確信度 */
    confidence?: number;
    /** 予測ホライゾン（日数） */
    horizon_days?: number;
    /** テスト精度（0〜1） */
    test_accuracy?: number;
    /** 使用したモデル名 */
    model?: string;
  };
  /** マルチタイムフレームの整合性サマリー */
  multi_timeframe: { alignment: string; alignment_label: string };
}

/**
 * ボラティリティ予測結果。
 *
 * `/api/analysis/volatility/{symbol}` エンドポイントのレスポンスに対応する。
 * ATR・日次ボラティリティの現状と予測が含まれる。
 */
export interface VolatilityPrediction {
  /** 通貨ペアシンボル */
  symbol: string;
  /** データソース */
  source: string;
  /** 現在価格 */
  current_price: number;
  /** 予測期間（日数） */
  forecast_days: number;
  /** 現在のボラティリティ指標 */
  current: {
    /** ATR（Average True Range）の絶対値 */
    atr: number;
    /** ATR を現在価格で割ったパーセント */
    atr_percent: number;
    /** 1 日あたりの標準偏差（%） */
    daily_volatility: number;
  };
  /** 予測ボラティリティ指標 */
  forecast: {
    /** 予測 ATR */
    atr: number;
    /** 予測 ATR パーセント */
    atr_percent: number;
    /** 予測日次ボラティリティ（%） */
    daily_volatility_pct: number;
    /** ボラティリティレジーム識別子（例: `"high"` / `"low"`） */
    regime: string;
    /** ボラティリティレジームの日本語ラベル */
    regime_label: string;
    /** ボラティリティトレンド方向（`"rising"` / `"falling"` / `"stable"`） */
    vol_trend: string;
    /** ボラティリティトレンドの日本語ラベル */
    vol_trend_label: string;
    /** 現在値との変化率（%） */
    change_vs_current_pct: number;
  };
  /** ML モデルによるボラティリティ予測 */
  ml: { status: string; model: string; predicted_atr: number };
  /** 人間が読めるボラティリティの解釈テキスト */
  interpretation: string;
}

/**
 * SNS（Reddit 等）の単一投稿データ。
 *
 * {@link SNSAnalysis} の `posts` 配列の要素型。
 */
export interface SNSPost {
  /** 投稿タイトル */
  title: string;
  /** 投稿 URL */
  url: string;
  /** 投稿先のサブレディット名 */
  subreddit: string;
  /** Reddit スコア（アップボート数 - ダウンボート数） */
  score: number;
  /** コメント数 */
  num_comments: number;
  /** 投稿日時（ISO 8601 形式） */
  published_at: string;
  /** データソース（例: `"reddit"`） */
  source: string;
}

/**
 * SNS センチメント分析の総合結果。
 *
 * `/api/analysis/sns/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface SNSAnalysis {
  /** 通貨ペアシンボル */
  symbol: string;
  /** データ収集日時 */
  collected_at: string;
  /** 収集したプラットフォーム名（例: `"reddit"`） */
  platform: string;
  /** 収集した投稿数 */
  post_count: number;
  /** 収集した投稿の配列 */
  posts: SNSPost[];
  /** ML によるセンチメント分析結果 */
  sentiment: MLNewsAnalysis;
  /** エンゲージメントレベル（例: `"high"` / `"medium"` / `"low"`） */
  engagement: string;
  /** 全投稿の合計スコア */
  total_score: number;
  /** 全投稿の合計コメント数 */
  total_comments: number;
  /** サブレディット別の投稿数マップ */
  subreddits: Record<string, number>;
  /** センチメントのサマリーテキスト */
  summary: string;
}

/**
 * 単一の経済指標データ。
 *
 * {@link EconomicAnalysis} の `indicators` 配列の要素型。
 */
export interface EconomicIndicator {
  /** 指標の識別キー（例: `"us_gdp"` / `"us_cpi"`） */
  key: string;
  /** 指標の表示名 */
  name: string;
  /** データソース名 */
  source: string;
  /** 最新データの日付 */
  latest_date?: string;
  /** 最新値 */
  value?: number;
  /** 前回値 */
  previous?: number;
  /** 予測値 */
  forecast?: number;
  /** 値の単位 */
  unit?: string;
  /** 市場への影響度（`"positive"` / `"negative"` / `"neutral"`） */
  impact: string;
  /** この指標が通貨ペアに与えるバイアス方向（`"bullish"` / `"bearish"` / `"neutral"`） */
  pair_direction: string;
  /** 指標の解説コメント */
  comment: string;
}

/**
 * 経済指標ベースの通貨ペア分析結果。
 *
 * `/api/analysis/economic/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface EconomicAnalysis {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 基軸通貨コード（例: `"USD"`） */
  base_currency: string;
  /** 決済通貨コード（例: `"JPY"`） */
  quote_currency: string;
  /** 経済指標から算出した通貨ペアのバイアス */
  pair_bias: "bullish" | "bearish" | "neutral";
  /** バイアスの日本語ラベル */
  pair_bias_label: string;
  /** バイアスの強さスコア（-100〜+100） */
  score: number;
  /** 分析に使用した経済指標の配列 */
  indicators: EconomicIndicator[];
  /** 今後の主要経済カレンダーイベント */
  upcoming_events: CalendarEvent[];
  /** 高インパクトのイベントアラート */
  high_impact_alerts: EventAlert[];
  /** 経済状況の総合的な概要テキスト */
  overview: string;
}

/**
 * インテリジェンスレポート（複数分析の統合）。
 *
 * `/api/analysis/intelligence/{symbol}` エンドポイントのレスポンスに対応する。
 * トレンド・ニュース・SNS・経済・ボラティリティの 5 つの分析が統合されている。
 */
export interface IntelligenceReport {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 各分析結果を加重平均した総合スコア（-100〜+100） */
  composite_score: number;
  /** 総合的な見通し方向 */
  outlook: "bullish" | "bearish" | "neutral";
  /** 見通しの日本語ラベル */
  outlook_label: string;
  /** トレンド予測 */
  trend: TrendPrediction;
  /** ニュース分析 */
  news: NewsAnalysisResult;
  /** SNS センチメント分析 */
  sns: SNSAnalysis;
  /** 経済指標分析 */
  economic: EconomicAnalysis;
  /** ボラティリティ予測 */
  volatility: VolatilityPrediction;
}

/**
 * Pro プラン向けの AI 統合シグナル結果。
 *
 * `/api/pro/signals/{symbol}` エンドポイントのレスポンスに対応する。
 * ルールベース・ML・AI の 3 つのシグナルが統合されている。
 */
export interface AISignalResult {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 現在価格 */
  price: number;
  /** 統合後の推奨アクション */
  action: "buy" | "sell" | "hold";
  /** 統合シグナルの確信度（0〜1） */
  confidence: number;
  /** 判断サマリーテキスト */
  summary: string;
  /** ルールベースのシグナル配列 */
  rule_signals: TradingSignal[];
  /** ML トレンド予測の要約 */
  trend_ml: { trend: string; label: string; confidence: number };
  /** AI（OpenAI）によるトレード判断（OpenAI 未設定時は `null`） */
  ai_decision?: AITradingDecision | null;
}

/**
 * Pro プラン向けのマーケットブリーフ（情報収集の総合サマリー）。
 *
 * `/api/pro/market-brief/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface MarketBrief {
  /** 通貨ペアシンボル */
  symbol: string;
  /** ニュース情報（記事一覧と ML センチメント） */
  news: { articles: NewsArticle[]; ml: MLNewsAnalysis };
  /** SNS 情報（サマリー・センチメント・エンゲージメント・投稿） */
  sns: { summary: string; sentiment: MLNewsAnalysis; engagement: string; posts: SNSPost[] };
  /** 経済指標サマリー */
  economic: {
    /** 通貨ペアバイアス識別子 */
    pair_bias: string;
    /** バイアスの日本語ラベル */
    pair_bias_label: string;
    /** 概要テキスト */
    overview: string;
    /** 経済指標リスト */
    indicators: EconomicIndicator[];
    /** 高インパクトアラートリスト */
    alerts: EventAlert[];
  };
  /** OpenAI による執行サマリー（設定済みの場合のみ） */
  openai?: {
    /** エグゼクティブサマリー */
    executive_summary?: string;
    /** 市場への影響評価 */
    market_impact?: string;
    /** 影響の方向性（`"bullish"` / `"bearish"` / `"neutral"`） */
    impact_direction?: string;
    /** 主要なドライバーのリスト */
    key_drivers?: string[];
    /** トレードへの示唆 */
    trading_implication?: string;
    /** 分析の確信度 */
    confidence?: number;
  } | null;
  /** OpenAI 未設定時のフォールバックサマリー */
  fallback_summary?: Record<string, string>;
}

/**
 * Pro プラン向けのトレードコーチング結果。
 *
 * `/api/pro/coaching/{symbol}` エンドポイントのレスポンスに対応する。
 * 過去の取引統計を基に AI がパーソナライズされたアドバイスを提供する。
 */
export interface CoachingResult {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 過去取引の統計データ（勝率・損益等） */
  trade_stats: Record<string, unknown>;
  /** AI コーチングの内容 */
  coaching: {
    /** 全体的な評価テキスト */
    overall_assessment?: string;
    /** トレードの強みのリスト */
    strengths?: string[];
    /** 改善が必要な弱点のリスト */
    weaknesses?: string[];
    /** 具体的な改善推奨事項のリスト */
    recommendations?: string[];
    /** 次に集中すべき課題 */
    next_focus?: string;
    /** リスク管理規律のスコア（0〜10） */
    risk_discipline_score?: number;
  } | null;
}

/**
 * ウォークフォワード最適化バックテストの結果。
 *
 * 戦略の堅牢性を評価するため、インサンプル最適化とアウトオブサンプル検証を
 * 複数ウィンドウにわたって繰り返す検証手法。
 */
export interface WalkForwardResult {
  /** 実行ステータス */
  status: string;
  /** 各ウィンドウの結果配列 */
  windows?: Array<{
    /** ウィンドウ番号 */
    window: number;
    /** インサンプル期間のバックテスト結果 */
    in_sample: SignalBacktest;
    /** アウトオブサンプル期間のバックテスト結果 */
    out_of_sample: SignalBacktest;
  }>;
  /** 全ウィンドウの集計サマリー */
  summary?: {
    /** 検証に使用したウィンドウ数 */
    window_count: number;
    /** インサンプルの平均勝率 */
    avg_in_sample_win_rate: number;
    /** アウトオブサンプルの平均勝率 */
    avg_out_of_sample_win_rate: number;
    /** 戦略の堅牢性評価ラベル */
    robustness_label: string;
  };
  /** エラーや情報メッセージ */
  message?: string;
}

/**
 * Pro プラン向けの高度なリスク分析結果。
 *
 * `/api/pro/risk/{symbol}` エンドポイントのレスポンスに対応する。
 * ドローダウン・ポジションサイジング・複数ペアへの資本配分が含まれる。
 */
export interface AdvancedRisk {
  /** 通貨ペアシンボル */
  symbol: string;
  /** 分析に使用した口座残高（USD） */
  account_balance: number;
  /** ドローダウン情報 */
  drawdown: {
    /** 最大ドローダウン率（%）*/
    max_drawdown_pct: number;
    /** 現在のドローダウン率（%）*/
    current_drawdown_pct: number;
  };
  /** ポジションサイズ計算結果 */
  position_sizing: PositionSizeResult;
  /** 損切り設定 */
  stop_loss: { price: number; pips: number; max_loss_usd: number };
  /** 利確設定 */
  take_profit: { price: number; pips: number; risk_reward: number };
  /** 複数通貨ペアへの資本配分 */
  capital_allocation: {
    /** 配分方法名 */
    method: string;
    /** 各ペアへの配分詳細 */
    pairs: Array<{ symbol: string; weight_pct: number; allocated_usd: number }>;
  };
  /** リスクバジェット（1 トレードあたり・最大同時エクスポージャー） */
  risk_budget: {
    /** 1 トレードあたりのリスク金額（USD） */
    per_trade_usd: number;
    /** 最大同時エクスポージャー合計（USD） */
    max_concurrent_exposure_usd: number;
    /** 推奨最大同時オープンポジション数 */
    max_open_positions_suggested: number;
  };
  /** 具体的なリスク管理の推奨事項リスト */
  recommendations: string[];
}

/**
 * マーケット分析（レジーム・キーレベル・モメンタム・相関・セッション）の総合結果。
 *
 * `/api/analysis/market/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface MarketAnalysis {
  /** 通貨ペアシンボル */
  symbol: string;
  /** データソース */
  source: string;
  /** 分析に使用した日数 */
  days: number;
  /** 現在の市場レジーム（トレンド相場・レンジ相場など） */
  regime: {
    /** レジーム識別子（例: `"strong_trend"` / `"range"`） */
    regime: string;
    /** レジームの日本語ラベル */
    label: string;
    /** レジームの強度スコア（0〜100） */
    strength: number;
    /** トレンドバイアス方向 */
    trend_bias: string;
    /** トレンドバイアスの日本語ラベル */
    trend_label: string;
    /** ATR の過去分布における百分位数（ボラティリティの相対的高低を示す） */
    atr_percentile: number;
    /** ボリンジャーバンド幅（%）— バンドの広狭を示す */
    bb_width_pct: number;
    /** 移動平均線間のスプレッド（%）*/
    ma_spread_pct: number;
    /** 20 日移動の傾き（%）*/
    slope_20d_pct: number;
  };
  /** サポート・レジスタンスの主要価格レベル */
  key_levels: {
    /** 現在価格 */
    current_price: number;
    /** サポートレベルの配列（高い順） */
    supports: number[];
    /** レジスタンスレベルの配列（低い順） */
    resistances: number[];
    /** 最も近いサポートレベル */
    nearest_support: number | null;
    /** 最も近いレジスタンスレベル */
    nearest_resistance: number | null;
    /** 最近サポートまでの距離（pips） */
    distance_to_support_pips: number | null;
    /** 最近レジスタンスまでの距離（pips） */
    distance_to_resistance_pips: number | null;
  };
  /** モメンタム指標の複合スコア */
  momentum: {
    /** モメンタムの総合スコア（-100〜+100） */
    score: number;
    /** モメンタムバイアス方向 */
    bias: string;
    /** バイアスの日本語ラベル */
    label: string;
    /** RSI 値 */
    rsi: number;
    /** MACD ヒストグラム値 */
    macd_histogram: number;
    /** 5 日変化率（%） */
    roc_5d_pct: number;
    /** 20 日変化率（%） */
    roc_20d_pct: number;
  };
  /** マルチタイムフレームのトレンド整合性 */
  multi_timeframe: {
    /** 整合性評価識別子 */
    alignment: string;
    /** 整合性評価の日本語ラベル */
    alignment_label: string;
    /** 各タイムフレームのトレンド・RSI */
    timeframes: Record<string, { trend: string; label: string; close: number; rsi: number | null }>;
  };
  /** 他の通貨ペアとの相関行列 */
  correlation: {
    /** 相関を計算した通貨ペアのリスト */
    pairs: string[];
    /** シンボル間の相関係数行列（-1〜+1） */
    matrix: Record<string, Record<string, number>>;
    /** 相関計算に使用した日数 */
    days: number;
    /** 有効なデータ観測数 */
    observations: number;
  };
  /** 現在のトレーディングセッション情報 */
  session: { session: string; label: string; note: string };
  /** 経済イベントリスクの評価 */
  event_risk: {
    /** イベントリスクレベル（`"high"` / `"medium"` / `"low"`） */
    level: string;
    /** イベントリスクの日本語ラベル */
    label: string;
    /** 最も近いイベントまでの時間（時間） */
    within_hours: number;
    /** 直近のハイインパクトイベント詳細リスト */
    alerts: Array<{ date: string; title: string; hours_until: number; impact: string }>;
  };
}

/**
 * リスクチェックリストの単一項目。
 *
 * トレード実行前に確認すべきリスク要因の評価結果。
 */
export interface RiskChecklistItem {
  /** チェック項目の名称 */
  item: string;
  /** 評価結果（`"pass"` = 問題なし、`"warn"` = 注意、`"fail"` = 問題あり） */
  status: "pass" | "warn" | "fail";
  /** 評価の詳細説明テキスト */
  detail: string;
}

/**
 * 総合リスクレポート（{@link AdvancedRisk} を拡張した完全版）。
 *
 * `/api/analysis/risk-report/{symbol}` エンドポイントのレスポンスに対応する。
 * VaR・シナリオ分析・ストレステスト・チェックリストが追加されている。
 */
export interface RiskReport extends AdvancedRisk {
  /** VaR（バリューアットリスク）- 指定した信頼水準での最大損失推定 */
  value_at_risk: {
    /** 信頼水準（例: `0.95` = 95%） */
    confidence: number;
    /** 1 日あたりの VaR（%） */
    daily_var_pct: number;
    /** 1 日あたりの VaR（USD） */
    daily_var_usd: number;
    /** VaR 計算に使用したデータ観測数 */
    observations: number;
  };
  /** シナリオ分析（ブル・ベース・ベアの 3 シナリオ） */
  scenarios: {
    /** 予測期間 */
    horizon: string;
    /** ブルシナリオ（楽観的） */
    bull: { price: number; change_pips: number; label: string };
    /** ベースシナリオ（中立的） */
    base: { price: number; change_pips: number; label: string };
    /** ベアシナリオ（悲観的） */
    bear: { price: number; change_pips: number; label: string };
  };
  /** ストレステスト（連続損失シミュレーション） */
  stress_test: {
    /** シミュレーションした連続損失回数 */
    consecutive_losses: number;
    /** 1 トレードあたりの損失額（USD） */
    loss_per_trade_usd: number;
    /** 連続損失後の合計損失額（USD） */
    total_loss_usd: number;
    /** 残余残高（USD） */
    remaining_balance_usd: number;
    /** 残余残高率（%）*/
    remaining_pct: number;
    /** ストレステスト結果の解釈テキスト */
    interpretation: string;
  };
  /** リスクスコアの概要 */
  risk_score: { score: number; level: string; label: string };
  /** 経済イベントリスク（{@link MarketAnalysis} と同形式） */
  event_risk: MarketAnalysis["event_risk"];
  /** 市場レジーム（{@link MarketAnalysis} と同形式） */
  market_regime: MarketAnalysis["regime"];
  /** トレード実行前のリスクチェックリスト */
  checklist: RiskChecklistItem[];
  /** トレード準備度の総合判定（`"green"` = GO / `"yellow"` = 注意 / `"red"` = 待機） */
  trade_readiness: "green" | "yellow" | "red";
  /** トレード準備度の日本語ラベル */
  trade_readiness_label: string;
}

/**
 * ポートフォリオ概要（複数口座・通貨ペア・直近注文のサマリー）。
 *
 * `/api/pro/portfolio` エンドポイントのレスポンスに対応する。
 */
export interface PortfolioOverview {
  /** 登録されている全ブローカー口座の配列 */
  accounts: Array<{
    /** 口座のデータベース ID */
    id: number;
    /** 口座の表示名 */
    name: string;
    /** ブローカー名 */
    broker: string;
    /** 現在の残高 */
    balance: number;
    /** デフォルト口座かどうか */
    is_default: boolean;
  }>;
  /** 登録口座数 */
  account_count: number;
  /** 全口座の合計残高 */
  total_balance: number;
  /** ウォッチリストの通貨ペア情報 */
  pairs: Array<{
    /** 通貨ペアシンボル */
    symbol: string;
    /** 現在価格 */
    price: number;
    /** 過去 30 日間の価格変化率（%） */
    change_30d_pct: number;
    /** 現在のオープンオーダー数 */
    open_orders: number;
  }>;
  /** 直近の注文履歴 */
  recent_orders: BrokerOrder[];
  /** ポートフォリオの総合サマリーテキスト */
  summary: string;
}

/**
 * チャットセッションの単一メッセージ。
 *
 * {@link ChatResponse} の `messages` 配列の要素型。
 */
export interface ChatMessage {
  /** メッセージの送信者ロール（`"user"` / `"assistant"` / `"system"`） */
  role: string;
  /** メッセージの本文テキスト */
  content: string;
  /** メッセージの作成日時 */
  created_at?: string;
}

/**
 * AI チャットのレスポンス。
 *
 * `/api/pro/chat` エンドポイントのレスポンスに対応する。
 */
export interface ChatResponse {
  /** チャットセッションの ID（次回リクエスト時に渡して会話を継続する） */
  session_id: number;
  /** チャットのコンテキストとなっている通貨ペアシンボル */
  symbol: string;
  /** AI の返答テキスト */
  reply: string;
  /** 会話履歴（過去メッセージを含む場合） */
  messages?: ChatMessage[];
  /** エラーメッセージ（失敗時） */
  error?: string;
}

/**
 * 自動売買システムの設定。
 *
 * `/api/autotrade/config` エンドポイントで取得・更新する設定モデル。
 */
export interface AutoTradeConfig {
  /** 自動売買が有効かどうか */
  enabled: boolean;
  /** 自動売買対象の通貨ペアシンボルリスト */
  symbols: string[];
  /** 取引モード（`"paper"` = 紙取引 / `"live"` = 実取引） */
  mode: "paper" | "live";
  /** 適用中の戦略プリセット ID */
  strategy_preset?: string;
  /** エントリーに必要な最低確信度（0〜1） */
  min_confidence: number;
  /** 1 トレードあたりのリスク率（%） */
  risk_percent: number;
  /** 設定上の口座残高（USD）（ポジションサイズ計算に使用） */
  account_balance: number;
  /** 使用するシグナルソースのリスト（例: `["rule", "ml", "ai"]`） */
  sources: string[];
  /** マルチタイムフレームのトレンド整合を必須条件にするかどうか */
  require_mtf_alignment: boolean;
  /** 経済イベント前後で取引を停止する時間（時間） */
  event_blackout_hours: number;
  /** 1 日あたりの最大取引数 */
  max_daily_trades: number;
  /** 同一ペアでの連続取引間隔（分） */
  cooldown_minutes: number;
  /** TradingView シグナルを自動実行するかどうか */
  auto_execute_tradingview: boolean;
  /** 反対シグナル発生時に自動で決済するかどうか */
  auto_exit_on_reverse?: boolean;
  /** 損切り注文を自動設定するかどうか */
  use_stop_loss?: boolean;
  /** 利確注文を自動設定するかどうか */
  use_take_profit?: boolean;
  /** リスクリワード比（利確幅 / 損切り幅） */
  risk_reward?: number;
  /** 最大ロット数（1 トレードあたりの上限） */
  max_lots: number;
  /** 最小ロット数（1 トレードあたりの下限） */
  min_lots: number;
  /** 最小取引単位（OANDA units） */
  min_units?: number;
  /** スケジューラーの実行間隔（分） */
  scheduler_interval_minutes: number;
  /** スケジューラーが有効かどうか */
  scheduler_enabled?: boolean;
  /** 同一ポジションへの追加エントリーを許可するかどうか */
  allow_add_to_position?: boolean;
}

/**
 * 自動売買の戦略プリセット定義。
 *
 * `/api/autotrade/presets` エンドポイントで取得できる事前定義の設定セット。
 */
export interface AutoTradePreset {
  /** プリセットの識別 ID */
  id: string;
  /** プリセットの表示ラベル */
  label: string;
  /** プリセットの説明テキスト */
  description: string;
  /** 取引スタイル（例: `"conservative"` / `"standard"` / `"aggressive"`） */
  style: string;
  /** このプリセットの最低確信度しきい値 */
  min_confidence: number;
  /** このプリセットのリスク率（%） */
  risk_percent: number;
  /** このプリセットのリスクリワード比 */
  risk_reward: number;
}

/**
 * 自動売買のシミュレーション結果（バックテスト + 資本充足性評価）。
 *
 * `/api/autotrade/simulate/{symbol}` エンドポイントのレスポンスに対応する。
 */
export interface AutoTradeSimulation {
  /** シミュレーション対象の通貨ペアシンボル */
  symbol: string;
  /** バックテスト統計 */
  backtest: {
    /** 総トレード数 */
    total_trades: number;
    /** 勝率（0〜1） */
    win_rate: number;
    /** 平均リターン（%） */
    avg_return_pct: number;
  };
  /** 資本充足性の評価 */
  capital: {
    /** 推奨最低証拠金（USD） */
    recommended_margin_usd: number;
    /** 安全な証拠金目安（USD） */
    safe_margin_usd: number;
    /** 資本評価に関する補足メモ */
    note: string;
  };
  /** 総合評価 */
  assessment: {
    /** 評価グレード（例: `"A"` / `"B"` / `"C"`） */
    grade: string;
    /** 評価で使用した勝率 */
    win_rate: number;
    /** 本番デプロイの準備ができているかどうか */
    ready_to_deploy: boolean;
    /** 評価の総合コメント */
    summary: string;
  };
}

/**
 * 自動売買のパフォーマンス統計。
 *
 * {@link AutoTradeStatus} の `performance` フィールドの型。
 */
export interface AutoTradePerformance {
  /** 実行サマリー */
  summary: {
    /** 総実行回数 */
    total_runs: number;
    /** 実際に発注した回数 */
    executed: number;
    /** ガード条件によってブロックされた回数 */
    blocked: number;
    /** スキップされた回数 */
    skipped?: number;
    /** 実行率（%） */
    execution_rate_pct: number;
    /** 実行時の平均確信度 */
    avg_confidence: number;
    /** 買いトレード数 */
    buy_trades?: number;
    /** 売りトレード数 */
    sell_trades?: number;
  };
  /** 損益（PnL）統計（取引履歴がある場合のみ） */
  pnl?: {
    /** 合計実現損益（USD） */
    total_realized_usd: number;
    /** 決済済みトレード数 */
    closed_trades: number;
    /** 勝ちトレード数 */
    wins: number;
    /** 負けトレード数 */
    losses: number;
    /** 勝率（%） */
    win_rate_pct: number;
    /** 週次 PnL の時系列データ */
    weekly: Array<{ week_start: string; realized_usd: number; trades: number; wins: number }>;
  };
  /** メンテナンスに関するヒントメッセージ */
  maintenance_hint: string;
  /** ブロック理由の上位ランキング */
  top_block_reasons: Array<{ reason: string; count: number }>;
  /** 直近の決済済みポジション */
  recent_closed?: Array<{
    /** 通貨ペアシンボル */
    symbol: string;
    /** 売買方向 */
    side: string;
    /** 実現損益（USD） */
    realized_pnl_usd?: number;
    /** 決済理由 */
    close_reason?: string;
    /** 決済日時 */
    closed_at?: string;
  }>;
}

/**
 * 自動売買が計画した注文の内容。
 *
 * {@link AutoTradeSignalSnapshot} の `order_plan` フィールドの型。
 */
export interface AutoTradeOrderPlan {
  /** 売買方向（`"buy"` / `"sell"`） */
  side: string;
  /** 取引単位（OANDA units） */
  units: number;
  /** ロット数 */
  lots?: number;
  /** 損切り価格 */
  stop_loss?: number;
  /** 利確価格 */
  take_profit?: number;
  /** エントリー価格 */
  entry_price?: number;
}

/**
 * 自動売買実行時のシグナルスナップショット。
 *
 * 実行時のシグナル状態を記録したもの（デバッグ・監査用）。
 */
export interface AutoTradeSignalSnapshot {
  /** 計画した注文の詳細 */
  order_plan?: AutoTradeOrderPlan;
  /** ガード条件によるブロック理由（ブロックされた場合） */
  guard_reason?: string;
  /** シグナル評価時の価格 */
  price?: number;
  /** 全シグナルソースを融合した結果 */
  fused?: Record<string, unknown>;
  /** 各シグナルソースの内訳 */
  breakdown?: Array<{ source: string; action: string; weight: number }>;
}

/**
 * 自動売買の単一実行ログ。
 *
 * `/api/autotrade/runs` で取得できる実行履歴の 1 件分。
 */
export interface AutoTradeRun {
  /** データベース上の実行 ID（新規実行では未設定） */
  id?: number;
  /** 通貨ペアシンボル */
  symbol: string;
  /** 実行されたアクション（`"buy"` / `"sell"` / `"hold"` / `"skip"` など） */
  action: string;
  /** 詳細な判断結果（`"executed"` / `"blocked"` / `"skipped"` など） */
  decision: string;
  /** シグナルの確信度（0〜1、計算不能な場合は `null`） */
  confidence: number | null;
  /** 発注した取引単位数 */
  units?: number | null;
  /** 約定価格 */
  fill_price?: number | null;
  /** 作成された注文の ID */
  order_id?: number | null;
  /** 実行のトリガー（例: `"scheduler"` / `"manual"` / `"tradingview"`） */
  trigger: string;
  /** 判断・ブロック・スキップの理由テキスト */
  reason: string;
  /** 実行時のシグナルスナップショット */
  signal_snapshot?: AutoTradeSignalSnapshot;
  /** 実行日時 */
  created_at?: string;
}

/**
 * 自動売買のシグナル評価結果（{@link AutoTradeRun} を拡張）。
 *
 * `/api/autotrade/evaluate/{symbol}` のレスポンス型。
 * `signal_snapshot` が必須になっている点が {@link AutoTradeRun} と異なる。
 */
export interface AutoTradeEvaluateResult extends AutoTradeRun {
  /** 評価時のシグナルスナップショット（必須） */
  signal_snapshot: AutoTradeSignalSnapshot;
}

/**
 * 自動売買システムの現在の稼働状況。
 *
 * `/api/autotrade/status` エンドポイントのレスポンスに対応する。
 */
export interface AutoTradeStatus {
  /** 現在の自動売買設定 */
  config: AutoTradeConfig;
  /** スケジューラーの状態 */
  scheduler: {
    /** グローバルスケジューラーが動作中かどうか */
    global_running: boolean;
    /** グローバルスケジューラーが有効化されているかどうか */
    global_enabled: boolean;
    /** このテナントのスケジューラーが有効かどうか */
    tenant_scheduler_enabled?: boolean;
    /** このテナントの自動売買が有効かどうか */
    tenant_autotrade_enabled?: boolean;
    /** 取引モード（`"paper"` / `"live"`） */
    trading_mode?: string;
    /** 最後にスケジューラーが実行された日時 */
    last_run_at: string | null;
    /** 最後の実行で処理されたシンボル数 */
    last_results_count: number;
    /** スケジューラーの実行間隔（分） */
    interval_minutes: number;
    /** 自動売買が有効なテナント数 */
    enabled_tenants: number;
    /** 分散ロックの設定情報（Redis を使用している場合） */
    distributed_lock?: { backend: string; redis_url_configured: boolean };
    /** @deprecated `global_running` を使用してください */
    scheduler_running?: boolean;
  };
  /** 直近の実行ログ */
  recent_runs: AutoTradeRun[];
  /** パフォーマンス統計（データがある場合） */
  performance?: AutoTradePerformance;
  /** 現在のオープンポジション一覧 */
  open_positions?: Array<{
    /** 通貨ペアシンボル */
    symbol: string;
    /** 売買方向 */
    side: string;
    /** 保有単位数 */
    units: number;
    /** エントリー価格 */
    entry_price: number;
    /** 損切り価格 */
    stop_loss?: number;
    /** 利確価格 */
    take_profit?: number;
  }>;
}
