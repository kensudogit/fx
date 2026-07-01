/**
 * @file AIDashboard.tsx
 * @description AI 分析ダッシュボード — OpenAI を使った FX マーケット分析画面
 *
 * OpenAI API を通じて以下 5 種類の AI 分析を実行・表示する：
 *   - 総合レポート   : ニュース・経済指標・テクニカルを一括分析
 *   - ニュース収集   : 最新 FX ニュースのセンチメント解析
 *   - 経済指標分析  : 主要指標の影響評価と通貨バイアス判定
 *   - 売買判断       : エントリー価格・SL/TP・RR 比の提案
 *   - リスク管理     : VaR・推奨ポジションサイズ・レバレッジ上限
 *
 * プラン制限（session.features.ai）と API キー設定状態を画面上に表示する。
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getSymbols,
  getAIStatus,
  getAINews,
  getAIFundamentalAnalysis,
  getAITradingDecision,
  getAIRisk,
  getAIReport,
} from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

import type {
  AINewsAnalysis,
  AIFundamentalAnalysis,
  AITradingDecision,
  AIRiskAssessment,
  AIFullReport,
} from "@/types";

/** タブ識別子の型。5 種類の AI 分析モードを切り替える */
type AITab = "news" | "fundamental" | "trading" | "risk" | "report";

/** OpenAI が返す英語センチメントを日本語に変換するマップ */
const SENTIMENT_LABELS: Record<string, string> = {
  bullish: "強気",
  bearish: "弱気",
  neutral: "中立",
};

/** 売買アクションの日本語ラベルマップ */
const ACTION_LABELS: Record<string, string> = {
  buy: "買い",
  sell: "売り",
  hold: "様子見",
};

/** リスクレベルの日本語ラベルマップ */
const RISK_LABELS: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  extreme: "極高",
};

/**
 * AIDashboard
 *
 * OpenAI API を利用した AI 分析のメインダッシュボード。
 * タブ切り替えに応じて対応する AI 分析 API を呼び出し、
 * 各結果を専用の子コンポーネント（NewsPanel / FundamentalPanel 等）に委譲して表示する。
 * 認証セッション情報を参照してプラン制限を画面上に案内する。
 */
export default function AIDashboard() {
  /** 認証コンテキストからセッション情報を取得（プラン制限チェックに使用） */
  const { session } = useAuth();
  /** 通貨ペア一覧（セレクトボックス用）— 初期値は空配列 */
  const [symbols, setSymbols] = useState<string[]>([]);
  /** 現在選択中の通貨ペア — デフォルト USDJPY */
  const [symbol, setSymbol] = useState("USDJPY");
  /** 口座残高（USD）— risk / report タブでポジションサイズ計算に利用 */
  const [accountBalance, setAccountBalance] = useState(10000);
  /** アクティブなタブ — デフォルトは report（総合レポート） */
  const [activeTab, setActiveTab] = useState<AITab>("report");
  /** API 呼び出し中フラグ */
  const [loading, setLoading] = useState(false);
  /** エラーメッセージ */
  const [error, setError] = useState<string | null>(null);
  /** OpenAI API の設定状態（true: 設定済み / false: 未設定 / null: 確認中） */
  const [aiReady, setAiReady] = useState<boolean | null>(null);

  /** ニュース分析の結果データ */
  const [news, setNews] = useState<AINewsAnalysis | null>(null);
  /** 経済指標分析の結果データ */
  const [fundamental, setFundamental] = useState<AIFundamentalAnalysis | null>(null);
  /** 売買判断の結果データ */
  const [trading, setTrading] = useState<AITradingDecision | null>(null);
  /** リスク管理の結果データ */
  const [risk, setRisk] = useState<AIRiskAssessment | null>(null);
  /** 総合レポートの結果データ（全分析を包含） */
  const [report, setReport] = useState<AIFullReport | null>(null);

  /**
   * マウント時の初期化副作用
   * - 通貨ペア一覧を取得してセレクトボックスを初期化する
   * - AI ステータスを確認して OPENAI_API_KEY の設定有無を把握する
   * 依存配列が空なのでコンポーネント初期表示時に 1 回のみ実行される
   */
  useEffect(() => {
    getSymbols().then((res) => setSymbols(res.symbols));
    getAIStatus()
      .then((s) => setAiReady(s.configured))
      .catch(() => setAiReady(false));
  }, []);

  /**
   * アクティブなタブに応じた AI 分析を実行する関数
   * useCallback でメモ化し、activeTab / symbol / accountBalance が変わるたびに再生成する
   * 「AI分析を実行」ボタン押下時に呼び出す（自動実行は行わない）
   */
  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // タブに対応するエンドポイントを呼び出す（処理時間 30 秒〜1 分程度）
      if (activeTab === "news") setNews(await getAINews(symbol));
      else if (activeTab === "fundamental") setFundamental(await getAIFundamentalAnalysis(symbol));
      else if (activeTab === "trading") setTrading(await getAITradingDecision(symbol));
      // リスク・レポートタブは口座残高を渡してポジションサイズ計算を行う
      else if (activeTab === "risk") setRisk(await getAIRisk(symbol, accountBalance));
      else setReport(await getAIReport(symbol, accountBalance));
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI分析に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [activeTab, symbol, accountBalance]);

  /** タブ定義配列 */
  const tabs: { key: AITab; label: string }[] = [
    { key: "report", label: "総合レポート" },
    { key: "news", label: "ニュース収集" },
    { key: "fundamental", label: "経済指標分析" },
    { key: "trading", label: "売買判断" },
    { key: "risk", label: "リスク管理" },
  ];

  return (
    <>
      <div className="page-header">
        <h1>AI 分析（OpenAI）</h1>
        <div className="controls">
          {/* 通貨ペア選択セレクトボックス */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          {/* リスク / レポートタブのみ口座残高入力を表示 */}
          {(activeTab === "risk" || activeTab === "report") && (
            <div className="select-wrapper">
              <input
                type="number"
                value={accountBalance}
                onChange={(e) => setAccountBalance(Number(e.target.value))}
                style={{
                  background: "var(--bg-secondary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "0.5rem 1rem",
                  width: 120,
                }}
                placeholder="口座残高"
              />
            </div>
          )}
          {/* 分析実行ボタン — API 呼び出し中は無効化 */}
          <button className="btn" onClick={runAnalysis} disabled={loading}>
            {loading ? "分析中..." : "AI分析を実行"}
          </button>
        </div>
      </div>

      {/* API 接続状態バッジ — OPENAI_API_KEY 設定・プラン制限の状態を案内 */}
      <div className="source-badge">
        Powered by OpenAI API
        {/* API キー未設定の場合は Railway 環境変数の確認を促す */}
        {aiReady === false && " — サーバー側 OPENAI_API_KEY が未設定です（Railway Variables を確認）"}
        {aiReady === true && " — 接続準備完了"}
        {/* プランで AI 機能が無効の場合に通知 */}
        {session && !session.features.ai && " — プランで AI が無効です"}
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* タブナビゲーション */}
      <div className="tabs" style={{ marginBottom: "1.5rem" }}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`tab ${activeTab === tab.key ? "active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ローディング中のインジケータ（処理時間が長いため目安時間を案内） */}
      {loading && <div className="loading">OpenAI で分析中です（30秒〜1分かかる場合があります）...</div>}

      {/* 各タブの結果を専用パネルコンポーネントに委譲して表示 */}
      {!loading && activeTab === "news" && news && <NewsPanel data={news} />}
      {!loading && activeTab === "fundamental" && fundamental && <FundamentalPanel data={fundamental} />}
      {!loading && activeTab === "trading" && trading && <TradingPanel data={trading} />}
      {!loading && activeTab === "risk" && risk && <RiskPanel data={risk} />}
      {!loading && activeTab === "report" && report && <ReportPanel data={report} />}

      {/* 初回表示時（全データ未取得）の説明カード */}
      {!loading && !news && !fundamental && !trading && !risk && !report && (
        <div className="card">
          <p style={{ color: "var(--text-secondary)" }}>
            「AI分析を実行」ボタンを押すと、OpenAI がニュース・経済指標・テクニカルを統合分析します。
          </p>
        </div>
      )}
    </>
  );
}

/**
 * NewsPanel
 *
 * AI ニュース分析結果を表示する子コンポーネント。
 * 左カード: センチメント・スコア・市場影響度・要約・キートピック
 * 右カード: 収集した記事リスト（リンク付き）
 *
 * @param data - getAINews() が返す AINewsAnalysis オブジェクト
 */
function NewsPanel({ data }: { data: AINewsAnalysis }) {
  return (
    <div className="grid-2">
      <div className="card">
        <h2>ニュース要約</h2>
        <div className="stat-grid" style={{ marginBottom: "1rem" }}>
          <div className="stat-item">
            <div className="label">センチメント</div>
            {/* 英語センチメントを日本語ラベルに変換（未知の値はそのまま表示） */}
            <div className="value">{SENTIMENT_LABELS[data.sentiment] ?? data.sentiment}</div>
          </div>
          <div className="stat-item">
            <div className="label">スコア</div>
            <div className="value">{data.sentiment_score}</div>
          </div>
          <div className="stat-item">
            <div className="label">市場影響度</div>
            <div className="value">{data.market_impact}</div>
          </div>
        </div>
        <p style={{ lineHeight: 1.8 }}>{data.summary}</p>
        {/* キートピックが 1 件以上ある場合のみバッジ表示 */}
        {data.key_topics?.length > 0 && (
          <div style={{ marginTop: "1rem" }}>
            <strong>キートピック:</strong>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
              {data.key_topics.map((t, i) => (
                <span key={i} className="source-badge">{t}</span>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="card">
        <h2>収集ニュース ({data.articles.length}件)</h2>
        {/* 記事リスト — 外部リンクは新規タブで開く */}
        <ul className="news-list">
          {data.articles.map((a, i) => (
            <li key={i}>
              <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a>
              <span className="news-meta">{a.source}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * FundamentalPanel
 *
 * 経済指標の AI 分析結果を表示する子コンポーネント。
 * 通貨ペアのバイアス・信頼度・基軸/決済通貨の分析、主要指標テーブルを表示する。
 *
 * @param data - getAIFundamentalAnalysis() が返す AIFundamentalAnalysis オブジェクト
 */
function FundamentalPanel({ data }: { data: AIFundamentalAnalysis }) {
  return (
    <div className="card">
      <h2>経済指標 AI 分析</h2>
      <div className="stat-grid" style={{ marginBottom: "1rem" }}>
        <div className="stat-item">
          <div className="label">バイアス</div>
          <div className="value">{SENTIMENT_LABELS[data.pair_bias] ?? data.pair_bias}</div>
        </div>
        <div className="stat-item">
          <div className="label">信頼度</div>
          <div className="value">{data.confidence}%</div>
        </div>
      </div>
      <p style={{ lineHeight: 1.8, marginBottom: "1rem" }}>{data.overview}</p>
      {/* 基軸通貨と決済通貨を 2 カラムで並べて比較表示 */}
      <div className="grid-2">
        <div>
          <h3>基軸通貨</h3>
          <p style={{ color: "var(--text-secondary)" }}>{data.base_currency_analysis}</p>
        </div>
        <div>
          <h3>決済通貨</h3>
          <p style={{ color: "var(--text-secondary)" }}>{data.quote_currency_analysis}</p>
        </div>
      </div>
      {/* 主要指標テーブル（1 件以上ある場合のみ表示） */}
      {data.key_indicators?.length > 0 && (
        <table style={{ marginTop: "1rem" }}>
          <thead>
            <tr><th>指標</th><th>影響</th><th>コメント</th></tr>
          </thead>
          <tbody>
            {data.key_indicators.map((ind, i) => (
              <tr key={i}>
                <td>{ind.name}</td>
                <td>{ind.impact}</td>
                <td>{ind.comment}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * TradingPanel
 *
 * AI 売買判断の結果を表示する子コンポーネント。
 * 判断（買い/売り/様子見）・信頼度・エントリー価格・SL/TP・RR 比を大きく表示し、
 * テクニカル・ファンダメンタル観点の根拠テキストと警告メッセージも提示する。
 * ReportPanel から再利用される共通コンポーネント。
 *
 * @param data - getAITradingDecision() が返す AITradingDecision オブジェクト
 */
function TradingPanel({ data }: { data: AITradingDecision }) {
  /** 判断（action）に応じてバッジの CSS クラスを決定 */
  const actionClass =
    data.action === "buy" ? "badge-buy" : data.action === "sell" ? "badge-sell" : "";
  return (
    <div className="card">
      <h2>売買判断</h2>
      <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stat-item">
          <div className="label">判断</div>
          <div className="value">
            <span className={`badge ${actionClass}`}>{ACTION_LABELS[data.action] ?? data.action}</span>
          </div>
        </div>
        <div className="stat-item">
          <div className="label">信頼度</div>
          <div className="value">{data.confidence}%</div>
        </div>
        <div className="stat-item">
          <div className="label">エントリー</div>
          <div className="value">{data.entry_price}</div>
        </div>
        <div className="stat-item">
          <div className="label">利確</div>
          {/* 利確価格は買いカラーで強調 */}
          <div className="value" style={{ color: "var(--buy)" }}>{data.take_profit}</div>
        </div>
        <div className="stat-item">
          <div className="label">損切り</div>
          {/* 損切り価格は売りカラーで強調 */}
          <div className="value" style={{ color: "var(--sell)" }}>{data.stop_loss}</div>
        </div>
        <div className="stat-item">
          <div className="label">RR比</div>
          <div className="value">{data.risk_reward_ratio}</div>
        </div>
      </div>
      <p style={{ lineHeight: 1.8 }}>{data.reasoning}</p>
      {/* テクニカル観点とファンダメンタル観点を横並びで比較 */}
      <div className="grid-2" style={{ marginTop: "1rem" }}>
        <div><h3>テクニカル</h3><p style={{ color: "var(--text-secondary)" }}>{data.technical_view}</p></div>
        <div><h3>ファンダメンタル</h3><p style={{ color: "var(--text-secondary)" }}>{data.fundamental_view}</p></div>
      </div>
      {/* 警告がある場合はシグナル売りスタイルで列挙 */}
      {data.warnings?.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          {data.warnings.map((w, i) => (
            <div key={i} className="signal-sell" style={{ fontSize: "0.85rem" }}>{w}</div>
          ))}
        </div>
      )}
      {/* OpenAI タイムアウト等でルールベース参考値にフォールバックした場合の注記 */}
      {"fallback" in data && (data as { fallback?: boolean }).fallback && (
        <p className="hint" style={{ marginTop: "0.75rem" }}>
          ※ OpenAI タイムアウト等のためルールベース参考値を表示しています。
        </p>
      )}
    </div>
  );
}

/**
 * RiskPanel
 *
 * AI リスク管理分析の結果を表示する子コンポーネント。
 * リスクレベル・スコア・推奨ポジションサイズ・最大損失・レバレッジ・SL/TP を表示する。
 * ReportPanel から再利用される共通コンポーネント。
 *
 * @param data - getAIRisk() が返す AIRiskAssessment オブジェクト
 */
function RiskPanel({ data }: { data: AIRiskAssessment }) {
  return (
    <div className="card">
      <h2>リスク管理</h2>
      <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stat-item">
          <div className="label">リスクレベル</div>
          {/* 英語レベルを日本語に変換（low/medium/high/extreme） */}
          <div className="value">{RISK_LABELS[data.risk_level] ?? data.risk_level}</div>
        </div>
        <div className="stat-item">
          <div className="label">リスクスコア</div>
          <div className="value">{data.risk_score}/100</div>
        </div>
        <div className="stat-item">
          <div className="label">推奨ポジション</div>
          <div className="value">{data.position_size_percent}% (${data.position_size_usd})</div>
        </div>
        <div className="stat-item">
          <div className="label">最大損失</div>
          <div className="value">{data.max_loss_percent}% (${data.max_loss_usd})</div>
        </div>
        <div className="stat-item">
          <div className="label">推奨レバレッジ</div>
          <div className="value">{data.recommended_leverage}x</div>
        </div>
        <div className="stat-item">
          <div className="label">損切り / 利確</div>
          <div className="value">{data.stop_loss_price} / {data.take_profit_price}</div>
        </div>
      </div>
      <p style={{ lineHeight: 1.8 }}>{data.volatility_assessment}</p>
      <p style={{ color: "var(--text-secondary)", marginTop: "0.5rem" }}>{data.market_conditions}</p>
      {/* 推奨事項リスト */}
      <h3 style={{ marginTop: "1rem" }}>推奨事項</h3>
      <ul className="bullet-list">
        {data.recommendations?.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
      {/* 取引を避けるべき条件は売りカラーで警告表示 */}
      <h3 style={{ marginTop: "1rem" }}>避けるべき条件</h3>
      <ul className="bullet-list">
        {data.do_not_trade_if?.map((r, i) => <li key={i} style={{ color: "var(--sell)" }}>{r}</li>)}
      </ul>
    </div>
  );
}

/**
 * ReportPanel
 *
 * AI 総合レポートを表示する子コンポーネント。
 * TradingPanel・NewsPanel・FundamentalPanel・RiskPanel を組み合わせて
 * 全分析結果を 1 ページに集約したレイアウトを提供する。
 *
 * @param data - getAIReport() が返す AIFullReport オブジェクト
 */
function ReportPanel({ data }: { data: AIFullReport }) {
  return (
    <div>
      {/* 売買判断を最上部に大きく表示 */}
      <TradingPanel data={data.trading_decision} />
      {/* ニュースと経済指標を 2 カラムで並べて表示 */}
      <div className="grid-2" style={{ marginTop: "1.5rem" }}>
        <NewsPanel data={data.news} />
        <FundamentalPanel data={data.fundamentals} />
      </div>
      {/* リスク管理は全幅で表示 */}
      <div style={{ marginTop: "1.5rem" }}>
        <RiskPanel data={data.risk_management} />
      </div>
    </div>
  );
}
