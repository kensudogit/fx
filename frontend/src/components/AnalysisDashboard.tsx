/**
 * @file AnalysisDashboard.tsx
 * @description マーケット分析ダッシュボード — ルールベース統合分析画面
 *
 * ルールベース ML・経済指標・SNS（Reddit）・ボラティリティなど
 * 8 種類の分析タブを提供する：
 *   - 総合       : 全分析スコアを統合した Intelligence Report
 *   - 相場環境   : レジーム・モメンタム・サポレジ・MTF・相関行列
 *   - リスク管理 : VaR・ドローダウン・ポジションサイジング・ストレステスト
 *   - トレンド予測: ルールベース + ML によるトレンド方向・信頼度
 *   - ニュース分析: ML キーワード + OpenAI による記事センチメント
 *   - SNS 分析   : Reddit 投稿のセンチメント集計
 *   - 経済指標   : 主要マクロ指標の影響評価
 *   - ボラ予測   : ATR / GARCH ベースのボラティリティ予測
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSymbols,
  getIntelligenceReport,
  getTrendPrediction,
  getAnalysisNews,
  getSNSAnalysis,
  getEconomicAnalysis,
  getVolatilityPrediction,
  getMarketAnalysis,
  getRiskReport,
} from "@/lib/api";
import type {
  IntelligenceReport,
  TrendPrediction,
  NewsAnalysisResult,
  SNSAnalysis,
  EconomicAnalysis,
  VolatilityPrediction,
  MarketAnalysis,
  RiskReport,
} from "@/types";

/** タブ識別子の型。8 種類の分析モードを切り替える */
type AnalysisTab =
  | "overview"
  | "market"
  | "risk"
  | "trend"
  | "news"
  | "sns"
  | "economic"
  | "volatility";

/** 英語センチメント → 日本語ラベル変換マップ */
const SENTIMENT: Record<string, string> = {
  bullish: "強気",
  bearish: "弱気",
  neutral: "中立",
};

/** 指標の通貨ペアへの影響方向 → 日本語ラベル変換マップ */
const IMPACT: Record<string, string> = {
  positive: "ポジティブ",
  negative: "ネガティブ",
  neutral: "中立",
};

/** 相場レジーム → 日本語ラベル変換マップ */
const REGIME_LABEL: Record<string, string> = {
  trending: "トレンド",
  ranging: "レンジ",
  volatile: "高ボラ",
};

/**
 * BiasBadge
 *
 * センチメント値（bullish / bearish / neutral）を色付きバッジで表示する
 * インラインコンポーネント。複数箇所で再利用される。
 *
 * @param value - "bullish" / "bearish" / "neutral" のいずれか
 */
function BiasBadge({ value }: { value: string }) {
  /** センチメント値に応じて CSS クラスを切り替え */
  const cls = value === "bullish" ? "badge-buy" : value === "bearish" ? "badge-sell" : "badge-neutral";
  return <span className={`badge ${cls}`}>{SENTIMENT[value] ?? value}</span>;
}

/**
 * ReadinessBadge
 *
 * 取引前の準備度合いを色付きバナーで表示するコンポーネント。
 * リスクタブのチェックリスト集計結果を視覚化する。
 *
 * @param level - "ready" / "caution" / "not_ready" など CSS クラスのサフィックス
 * @param label - バナーに表示するテキスト
 */
function ReadinessBadge({ level, label }: { level: string; label: string }) {
  return (
    <div className={`readiness-banner readiness-${level}`}>
      <span className="readiness-dot" />
      {label}
    </div>
  );
}

/**
 * AnalysisDashboard
 *
 * マーケット分析のメインダッシュボード。
 * タブ切り替えと通貨ペア変更を検知して自動的に対応 API を再呼び出しする。
 * リスクタブのみ口座残高とリスク許容率の追加入力が必要。
 */
export default function AnalysisDashboard() {
  /** 通貨ペア一覧（セレクトボックス用）*/
  const [symbols, setSymbols] = useState<string[]>([]);
  /** 現在選択中の通貨ペア — デフォルト USDJPY */
  const [symbol, setSymbol] = useState("USDJPY");
  /** アクティブなタブ — デフォルトは overview（総合） */
  const [tab, setTab] = useState<AnalysisTab>("overview");
  /** API 呼び出し中フラグ */
  const [loading, setLoading] = useState(false);
  /** エラーメッセージ */
  const [error, setError] = useState<string | null>(null);
  /** 口座残高（USD）— リスクタブのみ使用 */
  const [accountBalance, setAccountBalance] = useState(10000);
  /** リスク許容率（%）— リスクタブのみ使用、デフォルト 1% */
  const [riskPercent, setRiskPercent] = useState(1);

  /** 総合レポートデータ */
  const [report, setReport] = useState<IntelligenceReport | null>(null);
  /** 相場環境分析データ */
  const [market, setMarket] = useState<MarketAnalysis | null>(null);
  /** リスク管理レポートデータ */
  const [riskReport, setRiskReport] = useState<RiskReport | null>(null);
  /** トレンド予測データ */
  const [trend, setTrend] = useState<TrendPrediction | null>(null);
  /** ニュース分析データ */
  const [news, setNews] = useState<NewsAnalysisResult | null>(null);
  /** SNS 分析データ（Reddit） */
  const [sns, setSns] = useState<SNSAnalysis | null>(null);
  /** 経済指標分析データ */
  const [economic, setEconomic] = useState<EconomicAnalysis | null>(null);
  /** ボラティリティ予測データ */
  const [volatility, setVolatility] = useState<VolatilityPrediction | null>(null);

  /**
   * マウント時に通貨ペア一覧を取得する副作用
   * 依存配列が空なのでコンポーネント初期化時に 1 回のみ実行される
   */
  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  /**
   * アクティブなタブに応じたデータを取得する関数
   * useCallback でメモ化し、symbol / tab / accountBalance / riskPercent が変わるたびに再生成する
   */
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "overview") {
        // 全分析スコアを統合した Intelligence Report を取得
        setReport(await getIntelligenceReport(symbol));
      } else if (tab === "market") {
        // レジーム・モメンタム・サポレジ・相関行列を含む相場環境分析を取得
        setMarket(await getMarketAnalysis(symbol));
      } else if (tab === "risk") {
        // 口座残高・リスク許容率を渡してポジションサイズ・VaR を計算
        setRiskReport(await getRiskReport(symbol, accountBalance, riskPercent));
      } else if (tab === "trend") {
        setTrend(await getTrendPrediction(symbol));
      } else if (tab === "news") {
        setNews(await getAnalysisNews(symbol));
      } else if (tab === "sns") {
        setSns(await getSNSAnalysis(symbol));
      } else if (tab === "economic") {
        setEconomic(await getEconomicAnalysis(symbol));
      } else {
        setVolatility(await getVolatilityPrediction(symbol));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "分析に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [symbol, tab, accountBalance, riskPercent]);

  /**
   * tab / symbol / accountBalance / riskPercent が変化するたびに自動再取得する副作用
   * load 関数が useCallback でメモ化されているため依存配列は [load] だけで十分
   */
  useEffect(() => {
    load();
  }, [load]);

  /** タブ定義配列 */
  const tabs: { key: AnalysisTab; label: string }[] = [
    { key: "overview", label: "総合" },
    { key: "market", label: "相場環境" },
    { key: "risk", label: "リスク管理" },
    { key: "trend", label: "トレンド予測" },
    { key: "news", label: "ニュース分析" },
    { key: "sns", label: "SNS分析" },
    { key: "economic", label: "経済指標" },
    { key: "volatility", label: "ボラ予測" },
  ];

  /** いずれかのタブにデータがある場合は true（ローディング中の全画面スピナーを抑制） */
  const hasData =
    report || market || riskReport || trend || news || sns || economic || volatility;

  return (
    <>
      <div className="page-header">
        <h1>マーケット分析</h1>
        <div className="controls">
          {/* 通貨ペア選択セレクトボックス */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          {/* リスクタブのみ口座残高・リスク率の入力フィールドを追加表示 */}
          {tab === "risk" && (
            <>
              <label className="inline-field">
                口座 $
                <input
                  type="number"
                  min={100}
                  step={1000}
                  value={accountBalance}
                  onChange={(e) => setAccountBalance(Number(e.target.value))}
                />
              </label>
              <label className="inline-field">
                リスク %
                <input
                  type="number"
                  min={0.1}
                  max={10}
                  step={0.1}
                  value={riskPercent}
                  onChange={(e) => setRiskPercent(Number(e.target.value))}
                />
              </label>
            </>
          )}
          {/* 手動再分析ボタン — API 呼び出し中は無効化 */}
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            {loading ? "分析中..." : "再分析"}
          </button>
        </div>
      </div>

      {/* スクロール可能なタブナビゲーション（タブ数が多いためスクロール対応） */}
      <div className="tab-bar tab-bar-scroll">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`tab-btn ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {/* データ未取得時のみ全画面ローディングを表示（タブ切り替え中の既存データは維持） */}
      {loading && !hasData && <div className="loading">分析を実行中...</div>}

      {/* === 総合タブ: Intelligence Report の複合スコアと各分析のサマリーカードを表示 === */}
      {tab === "overview" && report && (
        <div className="analysis-overview">
          {/* 複合スコアカード（-100〜100 のスコア、プラスは強気色・マイナスは弱気色） */}
          <div className="card composite-card">
            <h2>{report.outlook_label}</h2>
            <div className="composite-score" data-sign={Math.sign(report.composite_score)}>
              {report.composite_score > 0 ? "+" : ""}
              {report.composite_score}
            </div>
            <p className="hint">トレンド・ニュース・SNS・経済指標・ボラを統合したスコア（-100〜100）</p>
          </div>
          {/* 各分析のサマリーカードを 2 カラムグリッドで並べる */}
          <div className="grid-2">
            <SummaryCard title="トレンド予測" bias={report.trend.trend} detail={report.trend.trend_label} />
            <SummaryCard
              title="ニュース"
              bias={report.news.ml.sentiment}
              detail={report.news.ml.summary}
            />
            <SummaryCard
              title="SNS"
              bias={report.sns.sentiment.sentiment}
              detail={report.sns.summary}
            />
            <SummaryCard
              title="経済指標"
              bias={report.economic.pair_bias}
              detail={report.economic.overview}
            />
            {/* ボラティリティが high レジームの場合はリスク警戒として bearish バッジを表示 */}
            <SummaryCard
              title="ボラティリティ"
              bias={report.volatility.forecast.regime === "high" ? "bearish" : "neutral"}
              detail={report.volatility.interpretation}
            />
          </div>
        </div>
      )}

      {/* === 相場環境タブ: レジーム・モメンタム・サポレジ・MTF・相関行列を 2 カラムで表示 === */}
      {tab === "market" && market && (
        <div className="market-analysis">
          <div className="grid-2">
            {/* 相場レジームカード */}
            <div className="card">
              <h2>
                相場レジーム — {market.symbol}{" "}
                <span className="badge badge-neutral">{REGIME_LABEL[market.regime.regime] ?? market.regime.regime}</span>
              </h2>
              <p>{market.regime.label}（強度 {market.regime.strength}/100）</p>
              <div className="stat-grid">
                <Stat label="トレンド方向" value={market.regime.trend_label} />
                <Stat label="ATR百分位" value={`${market.regime.atr_percentile}%`} />
                <Stat label="BB幅" value={`${market.regime.bb_width_pct}%`} />
                <Stat label="MA乖離" value={`${market.regime.ma_spread_pct}%`} />
                <Stat label="20日傾き" value={`${market.regime.slope_20d_pct}%`} />
              </div>
            </div>
            {/* モメンタムカード */}
            <div className="card">
              <h2>
                モメンタム <BiasBadge value={market.momentum.bias} />
              </h2>
              <p>{market.momentum.label}（スコア {market.momentum.score}）</p>
              <div className="stat-grid">
                <Stat label="RSI" value={String(market.momentum.rsi)} />
                <Stat label="MACD Hist" value={String(market.momentum.macd_histogram)} />
                <Stat label="5日ROC" value={`${market.momentum.roc_5d_pct}%`} />
                <Stat label="20日ROC" value={`${market.momentum.roc_20d_pct}%`} />
              </div>
            </div>
          </div>

          <div className="grid-2">
            {/* サポート / レジスタンスカード */}
            <div className="card">
              <h2>サポート / レジスタンス</h2>
              <div className="stat-grid">
                <Stat label="現在価格" value={String(market.key_levels.current_price)} />
                <Stat
                  label="最寄サポート"
                  value={
                    market.key_levels.nearest_support != null
                      ? `${market.key_levels.nearest_support} (${market.key_levels.distance_to_support_pips ?? "—"} pips)`
                      : "—"
                  }
                />
                <Stat
                  label="最寄レジスタンス"
                  value={
                    market.key_levels.nearest_resistance != null
                      ? `${market.key_levels.nearest_resistance} (${market.key_levels.distance_to_resistance_pips ?? "—"} pips)`
                      : "—"
                  }
                />
              </div>
              <div className="level-lists">
                <div>
                  <h3>サポート</h3>
                  {/* サポートレベルが 0 件の場合は「—」を表示 */}
                  <ul className="headline-list">
                    {market.key_levels.supports.length > 0 ? (
                      market.key_levels.supports.map((lv) => <li key={lv}>{lv}</li>)
                    ) : (
                      <li>—</li>
                    )}
                  </ul>
                </div>
                <div>
                  <h3>レジスタンス</h3>
                  {/* レジスタンスレベルが 0 件の場合は「—」を表示 */}
                  <ul className="headline-list">
                    {market.key_levels.resistances.length > 0 ? (
                      market.key_levels.resistances.map((lv) => <li key={lv}>{lv}</li>)
                    ) : (
                      <li>—</li>
                    )}
                  </ul>
                </div>
              </div>
            </div>
            {/* マルチタイムフレーム + 取引セッション + イベントリスクカード */}
            <div className="card">
              <h2>マルチタイムフレーム</h2>
              <p>{market.multi_timeframe.alignment_label}</p>
              <div className="stat-grid">
                <Stat label="日足" value={market.multi_timeframe.timeframes["1d"]?.label ?? "—"} />
                <Stat label="4H" value={market.multi_timeframe.timeframes["4h"]?.label ?? "—"} />
                <Stat label="日足RSI" value={String(market.multi_timeframe.timeframes["1d"]?.rsi ?? "—")} />
                <Stat label="4H RSI" value={String(market.multi_timeframe.timeframes["4h"]?.rsi ?? "—")} />
              </div>
              <h3 style={{ marginTop: "1rem" }}>取引セッション</h3>
              <p>
                {market.session.label} — {market.session.note}
              </p>
              <h3 style={{ marginTop: "1rem" }}>イベントリスク</h3>
              <p>{market.event_risk.label}</p>
              {/* 72 時間以内の高影響イベントがある場合のみ一覧表示 */}
              {market.event_risk.alerts.length > 0 && (
                <ul className="headline-list">
                  {market.event_risk.alerts.map((a, i) => (
                    <li key={i}>
                      {a.date} — {a.title}（あと {a.hours_until}h）
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* 通貨ペア相関行列テーブル — 相関係数を色分けして表示 */}
          <div className="card">
            <h2>通貨ペア相関（{market.correlation.days}日）</h2>
            <p className="hint">観測数: {market.correlation.observations} — 高相関ペアは同方向リスクに注意</p>
            <div className="correlation-wrap">
              <table className="data-table correlation-table">
                <thead>
                  <tr>
                    <th />
                    {market.correlation.pairs.map((p) => (
                      <th key={p}>{p}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {market.correlation.pairs.map((row) => (
                    <tr key={row}>
                      <th>{row}</th>
                      {market.correlation.pairs.map((col) => {
                        const v = market.correlation.matrix[row]?.[col] ?? 0;
                        /**
                         * 相関係数に応じてセルスタイルを切り替える：
                         * - 対角線（自己相関）: corr-self
                         * - |r| >= 0.7: corr-high（高相関・要注意）
                         * - |r| >= 0.4: corr-mid（中程度の相関）
                         */
                        const cls =
                          row === col ? "corr-self" : Math.abs(v) >= 0.7 ? "corr-high" : Math.abs(v) >= 0.4 ? "corr-mid" : "";
                        return (
                          <td key={col} className={cls}>
                            {row === col ? "—" : v.toFixed(2)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* === リスクタブ: 取引準備度バナー・VaR・チェックリスト・シナリオ分析を表示 === */}
      {tab === "risk" && riskReport && (
        <div className="risk-analysis">
          {/* 取引準備度バナー（ready / caution / not_ready で色が変わる） */}
          <ReadinessBadge level={riskReport.trade_readiness} label={riskReport.trade_readiness_label} />

          <div className="grid-2">
            {/* リスクスコアと主要指標カード */}
            <div className="card">
              <h2>リスクスコア</h2>
              {/* スコアの高低で文字色が変わる（data-level 属性で CSS 制御） */}
              <div className="risk-score-display" data-level={riskReport.risk_score.level}>
                {riskReport.risk_score.score}
                <span>/100</span>
              </div>
              <p>{riskReport.risk_score.label}</p>
              <div className="stat-grid">
                <Stat label="1日VaR (95%)" value={`$${riskReport.value_at_risk.daily_var_usd}`} />
                <Stat label="VaR%" value={`${riskReport.value_at_risk.daily_var_pct}%`} />
                <Stat label="最大DD" value={`${riskReport.drawdown.max_drawdown_pct}%`} />
                <Stat label="現在DD" value={`${riskReport.drawdown.current_drawdown_pct}%`} />
              </div>
            </div>
            {/* エントリー前チェックリストカード（各項目に pass/warn/fail のステータスアイコン） */}
            <div className="card">
              <h2>エントリー前チェックリスト</h2>
              <ul className="checklist">
                {riskReport.checklist.map((c) => (
                  <li key={c.item} className={`checklist-item checklist-${c.status}`}>
                    <span className="checklist-icon" aria-hidden />
                    <div>
                      <strong>{c.item}</strong>
                      <p className="hint">{c.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="grid-2">
            {/* ポジションサイジング・SL/TP カード */}
            <div className="card">
              <h2>ポジションサイズ</h2>
              <div className="stat-grid">
                <Stat label="推奨ロット" value={String(riskReport.position_sizing.recommended_lots)} />
                <Stat label="ストップ" value={`${riskReport.stop_loss.pips} pips`} />
                <Stat label="最大損失" value={`$${riskReport.stop_loss.max_loss_usd}`} />
                <Stat label="利確(RR2)" value={`${riskReport.take_profit.pips} pips`} />
                <Stat label="SL価格" value={String(riskReport.stop_loss.price)} />
                <Stat label="TP価格" value={String(riskReport.take_profit.price)} />
              </div>
            </div>
            {/* ATR ベースのシナリオ分析（強気/ベース/弱気）とストレステストカード */}
            <div className="card">
              <h2>シナリオ分析（ATRベース）</h2>
              <p className="hint">{riskReport.scenarios.horizon}</p>
              <div className="stat-grid">
                <Stat label="上振れ" value={`${riskReport.scenarios.bull.price} (+${riskReport.scenarios.bull.change_pips} pips)`} />
                <Stat label="ベース" value={String(riskReport.scenarios.base.price)} />
                <Stat label="下振れ" value={`${riskReport.scenarios.bear.price} (${riskReport.scenarios.bear.change_pips} pips)`} />
              </div>
              {/* 3 連敗ストレステスト — 連続損失が残高に与える影響を示す */}
              <h3 style={{ marginTop: "1rem" }}>ストレステスト（3連敗）</h3>
              <p>{riskReport.stress_test.interpretation}</p>
              <div className="stat-grid">
                <Stat label="連敗損失合計" value={`$${riskReport.stress_test.total_loss_usd}`} />
                <Stat label="残高" value={`$${riskReport.stress_test.remaining_balance_usd} (${riskReport.stress_test.remaining_pct}%)`} />
              </div>
            </div>
          </div>

          {/* リスク予算・複数ペアへの資金配分テーブル */}
          <div className="card">
            <h2>リスク予算・資金配分</h2>
            <div className="stat-grid">
              <Stat label="1トレード上限" value={`$${riskReport.risk_budget.per_trade_usd}`} />
              <Stat
                label="同時保有上限"
                value={`$${riskReport.risk_budget.max_concurrent_exposure_usd} / 最大${riskReport.risk_budget.max_open_positions_suggested}ポジ`}
              />
            </div>
            <table className="data-table" style={{ marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th>ペア</th>
                  <th>配分%</th>
                  <th>配分USD</th>
                </tr>
              </thead>
              <tbody>
                {riskReport.capital_allocation.pairs.map((p) => (
                  <tr key={p.symbol}>
                    <td>{p.symbol}</td>
                    <td>{p.weight_pct}%</td>
                    <td>${p.allocated_usd}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 style={{ marginTop: "1rem" }}>推奨アクション</h3>
            <ul className="headline-list">
              {riskReport.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* === トレンド予測タブ: ルールベース根拠・ML モデル結果を表示 === */}
      {tab === "trend" && trend && (
        <div className="card">
          <h2>
            トレンド予測 — {trend.symbol}{" "}
            <BiasBadge value={trend.trend} />
          </h2>
          <div className="stat-grid">
            <Stat label="現在価格" value={String(trend.current_price)} />
            <Stat label="予測期間" value={`${trend.horizon_days}日`} />
            <Stat label="信頼度" value={`${trend.confidence}%`} />
            <Stat label="MTF整合" value={trend.multi_timeframe.alignment_label} />
          </div>
          <h3>判定根拠（ルールベース）</h3>
          <ul className="headline-list">
            {trend.rule_based.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
          {/* ML モデルが成功した場合のみ予測精度を補足表示 */}
          {trend.ml.status === "success" && (
            <p className="hint">
              ML ({trend.ml.model}): {SENTIMENT[trend.ml.trend ?? "neutral"]} / テスト精度{" "}
              {trend.ml.test_accuracy}%
            </p>
          )}
        </div>
      )}

      {/* === ニュース分析タブ: ML センチメント・OpenAI 要約・記事ヘッドラインを表示 === */}
      {tab === "news" && news && (
        <div className="card">
          <h2>
            ニュース分析 — {news.symbol}{" "}
            <BiasBadge value={news.ml.sentiment} />
          </h2>
          <div className="stat-grid">
            <Stat label="MLスコア" value={String(news.ml.sentiment_score)} />
            <Stat label="強気ヒット" value={String(news.ml.bullish_hits)} />
            <Stat label="弱気ヒット" value={String(news.ml.bearish_hits)} />
            {/* OpenAI センチメントが存在する場合のみ追加表示 */}
            {news.openai && (
              <Stat label="OpenAI" value={SENTIMENT[news.openai.sentiment]} />
            )}
          </div>
          <p>{news.ml.summary}</p>
          {/* OpenAI 要約が存在する場合のみ表示 */}
          {news.openai?.summary && (
            <>
              <h3>OpenAI 要約</h3>
              <p>{news.openai.summary}</p>
            </>
          )}
          <h3>ヘッドライン</h3>
          <ul className="headline-list">
            {news.articles.map((a, i) => (
              <li key={i}>
                {/* URL がある記事はリンク表示、ない記事はテキストのみ */}
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer">
                    {a.title}
                  </a>
                ) : (
                  a.title
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* === SNS 分析タブ: Reddit 投稿のセンチメント集計テーブルを表示 === */}
      {tab === "sns" && sns && (
        <div className="card">
          <h2>
            SNS分析（Reddit）— {sns.symbol}{" "}
            <BiasBadge value={sns.sentiment.sentiment} />
          </h2>
          <div className="stat-grid">
            <Stat label="投稿数" value={String(sns.post_count)} />
            <Stat label="スコア合計" value={String(sns.total_score)} />
            <Stat label="コメント" value={String(sns.total_comments)} />
            <Stat label="エンゲージメント" value={sns.engagement} />
          </div>
          <p>{sns.summary}</p>
          {/* 投稿一覧テーブル（URL あればリンク、なければテキスト） */}
          <table className="data-table">
            <thead>
              <tr>
                <th>投稿</th>
                <th>Subreddit</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {sns.posts.map((p, i) => (
                <tr key={i}>
                  <td>
                    {p.url ? (
                      <a href={p.url} target="_blank" rel="noreferrer">
                        {p.title}
                      </a>
                    ) : (
                      p.title
                    )}
                  </td>
                  <td>r/{p.subreddit}</td>
                  <td>{p.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* === 経済指標タブ: 各指標の影響評価テーブルと高影響イベントアラートを表示 === */}
      {tab === "economic" && economic && (
        <div className="card">
          <h2>
            経済指標分析 — {economic.symbol}{" "}
            <BiasBadge value={economic.pair_bias} />
          </h2>
          <p>{economic.overview}</p>
          <table className="data-table">
            <thead>
              <tr>
                <th>指標</th>
                <th>最新値</th>
                <th>影響</th>
                <th>ペア方向</th>
                <th>コメント</th>
              </tr>
            </thead>
            <tbody>
              {economic.indicators.map((ind) => (
                <tr key={ind.key}>
                  <td>{ind.name}</td>
                  <td>
                    {ind.value}
                    {ind.unit ? ` ${ind.unit}` : ""}
                  </td>
                  <td>{IMPACT[ind.impact] ?? ind.impact}</td>
                  <td>
                    <BiasBadge value={ind.pair_direction} />
                  </td>
                  <td>{ind.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* 72 時間以内の高影響イベントがある場合のみアラートを表示 */}
          {economic.high_impact_alerts.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>72時間以内の高影響イベント</h3>
              <ul className="headline-list">
                {economic.high_impact_alerts.map((a, i) => (
                  <li key={i}>
                    {a.date} — {a.title}（あと {a.hours_until}h）
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* === ボラティリティ予測タブ: 現在・予測 ATR とレジームを表示 === */}
      {tab === "volatility" && volatility && (
        <div className="card">
          <h2>ボラティリティ予測 — {volatility.symbol}</h2>
          <p>{volatility.interpretation}</p>
          {/* 現在値と予測値を 2 カラムで比較表示 */}
          <div className="grid-2" style={{ marginTop: "1rem" }}>
            <div>
              <h3>現在</h3>
              <div className="stat-grid">
                <Stat label="ATR" value={String(volatility.current.atr)} />
                <Stat label="ATR%" value={`${volatility.current.atr_percent}%`} />
                <Stat label="日次ボラ" value={`${volatility.current.daily_volatility}%`} />
              </div>
            </div>
            <div>
              <h3>{volatility.forecast_days}日後予測</h3>
              <div className="stat-grid">
                <Stat label="予測ATR" value={String(volatility.forecast.atr)} />
                <Stat label="予測ATR%" value={`${volatility.forecast.atr_percent}%`} />
                <Stat label="レジーム" value={volatility.forecast.regime_label} />
                <Stat label="トレンド" value={volatility.forecast.vol_trend_label} />
              </div>
            </div>
          </div>
          <p className="hint">
            モデル: {volatility.ml.model} ({volatility.ml.status})
          </p>
        </div>
      )}
    </>
  );
}

/**
 * SummaryCard
 *
 * 総合タブで各分析カテゴリの要約を表示する小カード。
 * タイトル・センチメントバッジ・詳細テキストの 3 要素で構成される。
 *
 * @param title  - カードのタイトル（例: "トレンド予測"）
 * @param bias   - センチメント値（BiasBadge に渡す）
 * @param detail - サブテキスト（分析概要）
 */
function SummaryCard({
  title,
  bias,
  detail,
}: {
  /** カードのタイトル */
  title: string;
  /** センチメント値（"bullish" / "bearish" / "neutral"） */
  bias: string;
  /** 分析の概要テキスト */
  detail: string;
}) {
  return (
    <div className="card summary-card">
      <h3>
        {title} <BiasBadge value={bias} />
      </h3>
      <p className="hint">{detail}</p>
    </div>
  );
}

/**
 * Stat
 *
 * ラベルと値を 2 行で表示するシンプルな統計アイテムコンポーネント。
 * stat-grid 内の各セルとして利用される。
 *
 * @param label - 指標名（例: "RSI"）
 * @param value - 表示する値（文字列）
 */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-item">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
