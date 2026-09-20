/**
 * @file src/test/fixtures.ts
 * @description テスト用のダミーデータファクトリ集。
 *
 * バックエンド API のレスポンス型は項目数が非常に多いため、各ファクトリは
 * 「テスト対象コンポーネントが実際に参照するフィールド」のみを埋め、
 * `as unknown as T` で目的の型へキャストする。
 * 追加のフィールドが必要な場合は各ファクトリの引数 `overrides` で上書きできる。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import type {
  AIFullReport,
  AINewsAnalysis,
  AIFundamentalAnalysis,
  AIRiskAssessment,
  AISignalResult,
  AITradingDecision,
  AdvancedRisk,
  AutoTradeConfig,
  AutoTradeEvaluateResult,
  AutoTradePreset,
  AutoTradeSimulation,
  AutoTradeStatus,
  BrokerOrder,
  CalendarEvent,
  CoachingResult,
  DashboardData,
  EconomicAnalysis,
  EventAlert,
  FundamentalData,
  IntelligenceReport,
  MarketAnalysis,
  MarketBrief,
  MLPrediction,
  MultiTimeframeAnalysis,
  NewsAnalysisResult,
  OandaStatus,
  PortfolioOverview,
  PositionSizeResult,
  RiskReport,
  SNSAnalysis,
  SignalBacktest,
  TechnicalAnalysis,
  TradingSignal,
  TrendPrediction,
  VolatilityPrediction,
} from "@/types";
import type { AuthSession, BillingPlan } from "@/lib/api";

/**
 * ネストしたオブジェクト・配列要素も部分指定できる Partial。
 *
 * テストでは「見たいフィールドだけ差し替える」ことが多いため、
 * 各ファクトリの `overrides` はこの型を受け取る。
 */
export type DeepPartial<T> = T extends (infer U)[]
  ? DeepPartial<U>[]
  : T extends object
    ? { [K in keyof T]?: DeepPartial<T[K]> }
    : T;

/** 任意のオブジェクトを `overrides` でマージして型 T として返す内部ヘルパー */
function make<T>(base: object, overrides?: DeepPartial<T>): T {
  return { ...base, ...(overrides ?? {}) } as unknown as T;
}

/** テクニカル分析レスポンス（3 本足分の最小データ） */
export function technicalAnalysis(overrides?: DeepPartial<TechnicalAnalysis>): TechnicalAnalysis {
  return make<TechnicalAnalysis>(
    {
      symbol: "USDJPY",
      source: "database",
      timestamps: ["2026-01-01", "2026-01-02", "2026-01-03"],
      ohlcv: {
        open: [150.0, 150.5, 151.0],
        high: [151.0, 151.5, 152.0],
        low: [149.5, 150.0, 150.5],
        close: [150.5, 151.0, 151.5],
        volume: [100, 120, 110],
      },
      indicators: {
        ma: { sma_20: [150.1, 150.6, 151.1], sma_50: [149.9, 150.2, 150.8] },
        bollinger_bands: {
          upper: [152.0, 152.5, 153.0],
          middle: [150.2, 150.7, 151.2],
          lower: [148.4, 148.9, 149.4],
        },
        macd: { macd: [0.1, 0.2, 0.3], signal: [0.05, 0.1, 0.2], histogram: [0.05, 0.1, 0.1] },
        rsi: [45.1, 52.3, 61.7],
        stochastic: { k: [40, 55, 70], d: [42, 50, 65] },
        ichimoku: {
          tenkan: [150.2, 150.7, 151.2],
          kijun: [150.0, 150.4, 150.9],
          senkou_a: [150.1, 150.5, 151.0],
          senkou_b: [149.8, 150.1, 150.6],
        },
      },
      latest: { close: 151.5, rsi: 61.72, macd: 0.3456 },
    },
    overrides,
  );
}

/** ルールベースのトレードシグナル 1 件 */
export function tradingSignal(overrides?: DeepPartial<TradingSignal>): TradingSignal {
  return make<TradingSignal>(
    { indicator: "RSI", signal: "buy", value: 28.4, reason: "RSI が売られすぎ圏です" },
    overrides,
  );
}

/** 機械学習の価格予測レスポンス */
export function mlPrediction(overrides?: DeepPartial<MLPrediction>): MLPrediction {
  return make<MLPrediction>(
    { symbol: "USDJPY", status: "success", prediction: 152.34, test_r2: 0.87 },
    overrides,
  );
}

/** マルチタイムフレーム分析（日足・4 時間足） */
export function multiTimeframe(overrides?: DeepPartial<MultiTimeframeAnalysis>): MultiTimeframeAnalysis {
  return make<MultiTimeframeAnalysis>(
    {
      symbol: "USDJPY",
      alignment: "bullish",
      alignment_label: "日足・4H ともに上昇方向で一致",
      timeframes: {
        "1d": { trend: "bullish", label: "上昇", rsi: 61.7, signal_bias: "buy" },
        "4h": { trend: "bearish", label: "下降", rsi: 38.2, signal_bias: "sell" },
      },
    },
    overrides,
  );
}

/** シグナルバックテスト結果 */
export function signalBacktest(overrides?: DeepPartial<SignalBacktest>): SignalBacktest {
  return make<SignalBacktest>(
    {
      symbol: "USDJPY",
      win_rate: 58.3,
      total_trades: 24,
      avg_return_pct: 0.42,
      buy_trades: 14,
      sell_trades: 10,
      source: "database",
    },
    overrides,
  );
}

/** ポジションサイズ計算結果 */
export function positionSize(overrides?: DeepPartial<PositionSizeResult>): PositionSizeResult {
  return make<PositionSizeResult>(
    {
      symbol: "USDJPY",
      recommended_lots: 0.35,
      stop_pips: 42,
      atr_based_stop: true,
      max_loss_usd: 100,
      suggested_take_profit_pips: 84,
    },
    overrides,
  );
}

/** 経済イベントアラート 1 件 */
export function eventAlert(overrides?: DeepPartial<EventAlert>): EventAlert {
  return make<EventAlert>(
    { title: "米国雇用統計", country: "US", impact: "high", hours_until: 5.2, date: "2026-01-05" },
    overrides,
  );
}

/** 経済カレンダーのイベント 1 件 */
export function calendarEvent(overrides?: DeepPartial<CalendarEvent>): CalendarEvent {
  return make<CalendarEvent>(
    { date: "2026-01-05", title: "FOMC 政策金利発表", country: "US", impact: "high" },
    overrides,
  );
}

/** ファンダメンタルデータ（経済指標の時系列） */
export function fundamentalData(overrides?: DeepPartial<FundamentalData>): FundamentalData {
  return make<FundamentalData>(
    {
      events: {
        us_employment: {
          source: "FRED",
          data: [
            { date: "2025-12-05", value: 210, forecast: 190, previous: 180, unit: "千人" },
            { date: "2025-11-07", value: 180, forecast: null, previous: null, unit: null },
          ],
        },
        cpi: {
          source: "sample",
          data: [{ date: "2025-12-10", value: 3.1, forecast: 3.2, previous: 3.3, unit: "%" }],
        },
      },
    },
    overrides,
  );
}

/** AI ニュース分析 */
export function aiNews(overrides?: DeepPartial<AINewsAnalysis>): AINewsAnalysis {
  return make<AINewsAnalysis>(
    {
      sentiment: "bullish",
      sentiment_score: 0.62,
      market_impact: "中程度",
      summary: "米金利上昇観測からドル買いが優勢です。",
      key_topics: ["FOMC", "米雇用統計"],
      articles: [
        { title: "ドル円が年初来高値を更新", url: "https://example.com/a", source: "Reuters" },
      ],
    },
    overrides,
  );
}

/** AI ファンダメンタル分析 */
export function aiFundamental(overrides?: DeepPartial<AIFundamentalAnalysis>): AIFundamentalAnalysis {
  return make<AIFundamentalAnalysis>(
    {
      pair_bias: "bullish",
      confidence: 72,
      overview: "米経済指標は堅調です。",
      base_currency_analysis: "USD は金利差で優位。",
      quote_currency_analysis: "JPY は緩和継続で軟調。",
      key_indicators: [{ name: "CPI", impact: "positive", comment: "予想超え" }],
    },
    overrides,
  );
}

/** AI 売買判断 */
export function aiTradingDecision(overrides?: DeepPartial<AITradingDecision>): AITradingDecision {
  return make<AITradingDecision>(
    {
      action: "buy",
      confidence: 68,
      entry_price: 151.5,
      take_profit: 153.0,
      stop_loss: 150.8,
      risk_reward_ratio: 2.1,
      reasoning: "上位足のトレンドに沿った押し目買いです。",
      technical_view: "MA 上向き。",
      fundamental_view: "金利差が支援。",
      warnings: ["FOMC 前はボラティリティに注意"],
    },
    overrides,
  );
}

/** AI リスク評価 */
export function aiRisk(overrides?: DeepPartial<AIRiskAssessment>): AIRiskAssessment {
  return make<AIRiskAssessment>(
    {
      risk_level: "medium",
      risk_score: 48,
      position_size_percent: 2,
      position_size_usd: 200,
      max_loss_percent: 1,
      max_loss_usd: 100,
      recommended_leverage: 3,
      stop_loss_price: 150.8,
      take_profit_price: 153.0,
      volatility_assessment: "ボラティリティは平常域です。",
      market_conditions: "流動性は十分。",
      recommendations: ["ロットを抑える"],
      do_not_trade_if: ["指標発表の直前"],
    },
    overrides,
  );
}

/** AI 統合レポート（売買判断・ニュース・ファンダ・リスクの複合） */
export function aiFullReport(overrides?: DeepPartial<AIFullReport>): AIFullReport {
  return make<AIFullReport>(
    {
      trading_decision: aiTradingDecision(),
      news: aiNews(),
      fundamentals: aiFundamental(),
      risk_management: aiRisk(),
    },
    overrides,
  );
}

/** ニュース分析（ML + OpenAI） */
export function newsAnalysis(overrides?: DeepPartial<NewsAnalysisResult>): NewsAnalysisResult {
  return make<NewsAnalysisResult>(
    {
      symbol: "USDJPY",
      ml: {
        sentiment: "bullish",
        sentiment_score: 0.4,
        summary: "ML 判定は強気です。",
        bullish_hits: 7,
        bearish_hits: 2,
      },
      openai: { sentiment: "neutral", summary: "OpenAI は中立と判断しました。" },
      articles: [{ title: "ドル円続伸", url: "https://example.com/n1" }],
    },
    overrides,
  );
}

/** SNS（Reddit）分析 */
export function snsAnalysis(overrides?: DeepPartial<SNSAnalysis>): SNSAnalysis {
  return make<SNSAnalysis>(
    {
      symbol: "USDJPY",
      sentiment: { sentiment: "bearish", sentiment_score: -0.2 },
      post_count: 12,
      total_score: 340,
      total_comments: 88,
      engagement: "中",
      summary: "円高警戒の投稿が目立ちます。",
      posts: [{ title: "USDJPY thread", url: "https://example.com/p", subreddit: "forex", score: 42 }],
    },
    overrides,
  );
}

/** 経済指標分析 */
export function economicAnalysis(overrides?: DeepPartial<EconomicAnalysis>): EconomicAnalysis {
  return make<EconomicAnalysis>(
    {
      symbol: "USDJPY",
      pair_bias: "bullish",
      overview: "米指標優位の構図です。",
      indicators: [
        {
          key: "cpi",
          name: "CPI",
          value: 3.1,
          unit: "%",
          impact: "positive",
          pair_direction: "bullish",
          comment: "インフレ再燃",
        },
      ],
      high_impact_alerts: [{ date: "2026-01-05", title: "FOMC", hours_until: 30 }],
    },
    overrides,
  );
}

/** トレンド予測 */
export function trendPrediction(overrides?: DeepPartial<TrendPrediction>): TrendPrediction {
  return make<TrendPrediction>(
    {
      symbol: "USDJPY",
      trend: "bullish",
      trend_label: "上昇トレンド",
      current_price: 151.5,
      horizon_days: 5,
      confidence: 64,
      multi_timeframe: multiTimeframe(),
      rule_based: { reasons: ["SMA20 が SMA50 を上抜け"] },
      ml: { status: "success", model: "RandomForest", trend: "bullish", test_accuracy: 61.2 },
    },
    overrides,
  );
}

/** ボラティリティ予測 */
export function volatilityPrediction(
  overrides?: DeepPartial<VolatilityPrediction>,
): VolatilityPrediction {
  return make<VolatilityPrediction>(
    {
      symbol: "USDJPY",
      interpretation: "当面はボラティリティ低位で推移する見込みです。",
      forecast_days: 5,
      current: { atr: 0.82, atr_percent: 0.54, daily_volatility: 0.48 },
      forecast: {
        atr: 0.9,
        atr_percent: 0.6,
        regime: "normal",
        regime_label: "平常",
        vol_trend_label: "横ばい",
      },
      ml: { model: "GradientBoosting", status: "success" },
    },
    overrides,
  );
}

/** 統合インテリジェンスレポート（5 分析の複合） */
export function intelligenceReport(overrides?: DeepPartial<IntelligenceReport>): IntelligenceReport {
  return make<IntelligenceReport>(
    {
      symbol: "USDJPY",
      composite_score: 35,
      outlook_label: "やや強気",
      trend: trendPrediction(),
      news: newsAnalysis(),
      sns: snsAnalysis(),
      economic: economicAnalysis(),
      volatility: volatilityPrediction(),
    },
    overrides,
  );
}

/** 相場環境分析（レジーム・S/R・相関） */
export function marketAnalysis(overrides?: DeepPartial<MarketAnalysis>): MarketAnalysis {
  return make<MarketAnalysis>(
    {
      symbol: "USDJPY",
      regime: {
        regime: "trending",
        label: "明確なトレンド",
        strength: 72,
        trend_label: "上昇",
        atr_percentile: 55,
        bb_width_pct: 1.8,
        ma_spread_pct: 0.6,
        slope_20d_pct: 1.2,
      },
      momentum: {
        bias: "bullish",
        label: "強い上昇モメンタム",
        score: 62,
        rsi: 61.7,
        macd_histogram: 0.1,
        roc_5d_pct: 0.8,
        roc_20d_pct: 2.4,
      },
      key_levels: {
        current_price: 151.5,
        nearest_support: 150.2,
        nearest_resistance: 152.8,
        distance_to_support_pips: 130,
        distance_to_resistance_pips: 130,
        supports: [150.2, 149.0],
        resistances: [152.8, 154.0],
      },
      multi_timeframe: multiTimeframe(),
      session: { label: "ロンドン", note: "流動性が高い時間帯です。" },
      event_risk: {
        label: "72 時間以内に高影響イベントあり",
        alerts: [{ date: "2026-01-05", title: "FOMC", hours_until: 30 }],
      },
      correlation: {
        days: 60,
        observations: 60,
        pairs: ["USDJPY", "EURUSD"],
        matrix: { USDJPY: { USDJPY: 1, EURUSD: -0.72 }, EURUSD: { USDJPY: -0.72, EURUSD: 1 } },
      },
    },
    overrides,
  );
}

/** 高度リスク管理（AI Pro のリスクタブ） */
export function advancedRisk(overrides?: DeepPartial<AdvancedRisk>): AdvancedRisk {
  return make<AdvancedRisk>(
    {
      symbol: "USDJPY",
      drawdown: { max_drawdown_pct: 12.4, current_drawdown_pct: 3.1 },
      position_sizing: { recommended_lots: 0.4 },
      stop_loss: { price: 150.8, pips: 42, max_loss_usd: 100 },
      take_profit: { price: 153.0, pips: 84 },
      capital_allocation: { pairs: [{ symbol: "USDJPY", weight_pct: 60, allocated_usd: 6000 }] },
      recommendations: ["同方向ペアの同時保有を避ける"],
    },
    overrides,
  );
}

/** 統合リスクレポート（/analysis のリスク管理タブ） */
export function riskReport(overrides?: DeepPartial<RiskReport>): RiskReport {
  return make<RiskReport>(
    {
      ...advancedRisk(),
      trade_readiness: "caution",
      trade_readiness_label: "条件付きでエントリー可",
      risk_score: { score: 48, level: "medium", label: "リスクは中程度です" },
      value_at_risk: { daily_var_usd: 120, daily_var_pct: 1.2 },
      checklist: [{ item: "MTF 整合", status: "ok", detail: "日足・4H ともに上昇" }],
      scenarios: {
        horizon: "5 営業日",
        bull: { price: 153.2, change_pips: 170 },
        base: { price: 151.5 },
        bear: { price: 149.8, change_pips: -170 },
      },
      stress_test: {
        interpretation: "3 連敗しても運用継続可能です。",
        total_loss_usd: 300,
        remaining_balance_usd: 9700,
        remaining_pct: 97,
      },
      risk_budget: {
        per_trade_usd: 100,
        max_concurrent_exposure_usd: 300,
        max_open_positions_suggested: 3,
      },
    },
    overrides,
  );
}

/** OANDA 接続ステータス */
export function oandaStatus(overrides?: DeepPartial<OandaStatus>): OandaStatus {
  return make<OandaStatus>(
    {
      configured: false,
      mode: "practice",
      balance: 10000,
      currency: "USD",
      unrealized_pl: 12.5,
      message: "OANDA 未設定のためペーパー取引です",
    },
    overrides,
  );
}

/** ブローカー注文 1 件 */
export function brokerOrder(overrides?: DeepPartial<BrokerOrder>): BrokerOrder {
  return make<BrokerOrder>(
    {
      id: 1,
      symbol: "USDJPY",
      side: "buy",
      units: 1000,
      fill_price: 151.52,
      status: "filled",
      broker: "paper",
      created_at: "2026-01-02T03:04:05Z",
    },
    overrides,
  );
}

/** 統合ダッシュボードのレスポンス */
export function dashboardData(overrides?: DeepPartial<DashboardData>): DashboardData {
  return make<DashboardData>(
    {
      symbol: "USDJPY",
      price: 151.5,
      signals: [tradingSignal()],
      stack: { api: "FastAPI", frontend: "Next.js", note: "同一オリジンプロキシ" },
      tradingview_signals: [
        {
          id: 1,
          action: "buy",
          price: 151.4,
          strategy: "RSI+MACD",
          received_at: "2026-01-02T01:00:00Z",
        },
      ],
      backtest_backtrader: {
        status: "success",
        strategy: "RsiMacd",
        initial_cash: 10000,
        final_value: 10850,
        total_return_pct: 8.5,
      },
      backtest_simple: signalBacktest(),
      oanda: oandaStatus(),
      recent_orders: [brokerOrder()],
      openai_configured: true,
    },
    overrides,
  );
}

/** AI Pro の売買シグナル */
export function aiSignalResult(overrides?: DeepPartial<AISignalResult>): AISignalResult {
  return make<AISignalResult>(
    {
      symbol: "USDJPY",
      action: "buy",
      confidence: 71,
      price: 151.5,
      summary: "ルール・ML・AI の 3 者が買いで一致しました。",
      rule_signals: [tradingSignal()],
    },
    overrides,
  );
}

/** AI Pro の市場ブリーフ */
export function marketBrief(overrides?: DeepPartial<MarketBrief>): MarketBrief {
  return make<MarketBrief>(
    {
      symbol: "USDJPY",
      openai: {
        executive_summary: "ドル高基調が継続しています。",
        trading_implication: "押し目買い優先。",
      },
      news: { ml: { sentiment: "bullish" }, articles: [{ title: "ドル円上昇" }] },
      sns: { summary: "SNS は強気優勢です。" },
      economic: { overview: "米指標は堅調です。" },
    },
    overrides,
  );
}

/** AI Pro のコーチング結果 */
export function coachingResult(overrides?: DeepPartial<CoachingResult>): CoachingResult {
  return make<CoachingResult>(
    {
      symbol: "USDJPY",
      coaching: {
        overall_assessment: "リスク管理は良好です。",
        recommendations: ["ロットを一定に保つ"],
        next_focus: "損切り位置の一貫性",
      },
    },
    overrides,
  );
}

/** AI Pro のポートフォリオ概要 */
export function portfolioOverview(overrides?: DeepPartial<PortfolioOverview>): PortfolioOverview {
  return make<PortfolioOverview>(
    {
      summary: "2 口座・2 通貨ペアを運用中です。",
      total_balance: 25000,
      accounts: [{ id: 1, name: "メイン", broker: "oanda", balance: 15000 }],
      pairs: [{ symbol: "USDJPY", price: 151.5, change_30d_pct: 1.8, open_orders: 2 }],
    },
    overrides,
  );
}

/** 自動取引の設定 */
export function autoTradeConfig(overrides?: DeepPartial<AutoTradeConfig>): AutoTradeConfig {
  return make<AutoTradeConfig>(
    {
      enabled: false,
      mode: "paper",
      strategy_preset: "balanced",
      min_confidence: 65,
      risk_percent: 1,
      account_balance: 10000,
      max_daily_trades: 3,
      cooldown_minutes: 60,
      event_blackout_hours: 12,
      symbols: ["USDJPY"],
      sources: ["ai", "technical"],
      require_mtf_alignment: false,
      auto_execute_tradingview: false,
      use_stop_loss: true,
      use_take_profit: true,
      auto_exit_on_reverse: true,
    },
    overrides,
  );
}

/** 自動取引のプリセット 1 件 */
export function autoTradePreset(overrides?: DeepPartial<AutoTradePreset>): AutoTradePreset {
  return make<AutoTradePreset>(
    {
      id: "balanced",
      label: "バランス",
      description: "標準的なリスクとリターンのバランス型",
      min_confidence: 65,
      risk_reward: 2,
    },
    overrides,
  );
}

/** 自動取引の稼働ステータス */
export function autoTradeStatus(overrides?: DeepPartial<AutoTradeStatus>): AutoTradeStatus {
  return make<AutoTradeStatus>(
    {
      scheduler: {
        tenant_scheduler_enabled: true,
        global_running: true,
        trading_mode: "paper",
        interval_minutes: 15,
        last_run_at: "2026-01-02T03:00:00Z",
        distributed_lock: { backend: "redis" },
      },
      performance: {
        summary: { execution_rate_pct: 42.5, executed: 17, blocked: 23, avg_confidence: 66.1 },
        pnl: {
          total_realized_usd: 245.5,
          win_rate_pct: 61.5,
          closed_trades: 13,
          weekly: [{ week_start: "2025-12-29", realized_usd: 120.5, trades: 5, wins: 3 }],
        },
        maintenance_hint: "週次で設定を見直してください。",
      },
      open_positions: [
        {
          symbol: "USDJPY",
          side: "buy",
          units: 1000,
          entry_price: 151.2,
          stop_loss: 150.5,
          take_profit: 152.6,
        },
      ],
      recent_runs: [
        {
          id: 1,
          symbol: "USDJPY",
          action: "buy",
          decision: "executed",
          confidence: 71,
          units: 1000,
          trigger: "manual",
          reason: "AI シグナルが閾値を超過",
          created_at: "2026-01-02T03:00:00Z",
        },
      ],
    },
    overrides,
  );
}

/** 自動取引の評価結果（ドライラン） */
export function autoTradeEvaluation(
  overrides?: DeepPartial<AutoTradeEvaluateResult>,
): AutoTradeEvaluateResult {
  return make<AutoTradeEvaluateResult>(
    {
      symbol: "USDJPY",
      action: "buy",
      decision: "ready",
      confidence: 71,
      reason: "全条件を満たしています",
      trigger: "manual",
      signal_snapshot: {
        order_plan: { side: "buy", units: 1000, stop_loss: 150.5, take_profit: 152.6 },
      },
    },
    overrides,
  );
}

/** 自動取引の運用前シミュレーション結果 */
export function autoTradeSimulation(
  overrides?: DeepPartial<AutoTradeSimulation>,
): AutoTradeSimulation {
  return make<AutoTradeSimulation>(
    {
      symbol: "USDJPY",
      backtest: { win_rate: 58.3, total_trades: 24 },
      capital: { recommended_margin_usd: 12000, safe_margin_usd: 20000 },
      assessment: {
        grade: "B",
        ready_to_deploy: true,
        summary: "実運用可能な水準です。",
      },
    },
    overrides,
  );
}

/** 認証済みセッション（AuthContext / NavBar / 設定ページ用） */
export function authSession(overrides?: DeepPartial<AuthSession>): AuthSession {
  return make<AuthSession>(
    {
      user: { id: 1, email: "trader@example.com", role: "admin", tenant_id: 1 },
      tenant: { id: 1, name: "Example 株式会社", slug: "example", plan: "free" },
      usage: {
        daily_calls: 40,
        daily_limit: 100,
        remaining: 60,
        usage_percent: 40,
        usage_level: "ok",
      },
      features: { ai: true, ai_pro: false, autotrade: false, analysis_basic: true },
      billing: { stripe_customer: false, stripe_subscription: false },
    },
    overrides,
  );
}

/** 課金プラン 1 件 */
export function billingPlan(overrides?: DeepPartial<BillingPlan>): BillingPlan {
  return make<BillingPlan>(
    {
      id: "pro",
      name: "Pro",
      price_monthly_usd: 49,
      daily_api_limit: 10000,
      features: {
        analysis_basic: true,
        ai: true,
        ai_pro: true,
        oanda_orders: true,
        autotrade: true,
        analysis_intelligence: true,
        api_keys: 5,
      },
    },
    overrides,
  );
}
