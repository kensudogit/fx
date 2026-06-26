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

type AITab = "news" | "fundamental" | "trading" | "risk" | "report";

const SENTIMENT_LABELS: Record<string, string> = {
  bullish: "強気",
  bearish: "弱気",
  neutral: "中立",
};

const ACTION_LABELS: Record<string, string> = {
  buy: "買い",
  sell: "売り",
  hold: "様子見",
};

const RISK_LABELS: Record<string, string> = {
  low: "低",
  medium: "中",
  high: "高",
  extreme: "極高",
};

export default function AIDashboard() {
  const { session } = useAuth();
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [accountBalance, setAccountBalance] = useState(10000);
  const [activeTab, setActiveTab] = useState<AITab>("report");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiReady, setAiReady] = useState<boolean | null>(null);

  const [news, setNews] = useState<AINewsAnalysis | null>(null);
  const [fundamental, setFundamental] = useState<AIFundamentalAnalysis | null>(null);
  const [trading, setTrading] = useState<AITradingDecision | null>(null);
  const [risk, setRisk] = useState<AIRiskAssessment | null>(null);
  const [report, setReport] = useState<AIFullReport | null>(null);

  useEffect(() => {
    getSymbols().then((res) => setSymbols(res.symbols));
    getAIStatus()
      .then((s) => setAiReady(s.configured))
      .catch(() => setAiReady(false));
  }, []);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (activeTab === "news") setNews(await getAINews(symbol));
      else if (activeTab === "fundamental") setFundamental(await getAIFundamentalAnalysis(symbol));
      else if (activeTab === "trading") setTrading(await getAITradingDecision(symbol));
      else if (activeTab === "risk") setRisk(await getAIRisk(symbol, accountBalance));
      else setReport(await getAIReport(symbol, accountBalance));
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI分析に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [activeTab, symbol, accountBalance]);

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
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
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
          <button className="btn" onClick={runAnalysis} disabled={loading}>
            {loading ? "分析中..." : "AI分析を実行"}
          </button>
        </div>
      </div>

      <div className="source-badge">
        Powered by OpenAI API
        {aiReady === false && " — サーバー側 OPENAI_API_KEY が未設定です（Railway Variables を確認）"}
        {aiReady === true && " — 接続準備完了"}
        {session && !session.features.ai && " — プランで AI が無効です"}
      </div>

      {error && <div className="error-banner">{error}</div>}

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

      {loading && <div className="loading">OpenAI で分析中です（30秒〜1分かかる場合があります）...</div>}

      {!loading && activeTab === "news" && news && <NewsPanel data={news} />}
      {!loading && activeTab === "fundamental" && fundamental && <FundamentalPanel data={fundamental} />}
      {!loading && activeTab === "trading" && trading && <TradingPanel data={trading} />}
      {!loading && activeTab === "risk" && risk && <RiskPanel data={risk} />}
      {!loading && activeTab === "report" && report && <ReportPanel data={report} />}

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

function NewsPanel({ data }: { data: AINewsAnalysis }) {
  return (
    <div className="grid-2">
      <div className="card">
        <h2>ニュース要約</h2>
        <div className="stat-grid" style={{ marginBottom: "1rem" }}>
          <div className="stat-item">
            <div className="label">センチメント</div>
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

function TradingPanel({ data }: { data: AITradingDecision }) {
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
          <div className="value" style={{ color: "var(--buy)" }}>{data.take_profit}</div>
        </div>
        <div className="stat-item">
          <div className="label">損切り</div>
          <div className="value" style={{ color: "var(--sell)" }}>{data.stop_loss}</div>
        </div>
        <div className="stat-item">
          <div className="label">RR比</div>
          <div className="value">{data.risk_reward_ratio}</div>
        </div>
      </div>
      <p style={{ lineHeight: 1.8 }}>{data.reasoning}</p>
      <div className="grid-2" style={{ marginTop: "1rem" }}>
        <div><h3>テクニカル</h3><p style={{ color: "var(--text-secondary)" }}>{data.technical_view}</p></div>
        <div><h3>ファンダメンタル</h3><p style={{ color: "var(--text-secondary)" }}>{data.fundamental_view}</p></div>
      </div>
      {data.warnings?.length > 0 && (
        <div style={{ marginTop: "1rem" }}>
          {data.warnings.map((w, i) => (
            <div key={i} className="signal-sell" style={{ fontSize: "0.85rem" }}>{w}</div>
          ))}
        </div>
      )}
      {"fallback" in data && (data as { fallback?: boolean }).fallback && (
        <p className="hint" style={{ marginTop: "0.75rem" }}>
          ※ OpenAI タイムアウト等のためルールベース参考値を表示しています。
        </p>
      )}
    </div>
  );
}

function RiskPanel({ data }: { data: AIRiskAssessment }) {
  return (
    <div className="card">
      <h2>リスク管理</h2>
      <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
        <div className="stat-item">
          <div className="label">リスクレベル</div>
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
      <h3 style={{ marginTop: "1rem" }}>推奨事項</h3>
      <ul className="bullet-list">
        {data.recommendations?.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
      <h3 style={{ marginTop: "1rem" }}>避けるべき条件</h3>
      <ul className="bullet-list">
        {data.do_not_trade_if?.map((r, i) => <li key={i} style={{ color: "var(--sell)" }}>{r}</li>)}
      </ul>
    </div>
  );
}

function ReportPanel({ data }: { data: AIFullReport }) {
  return (
    <div>
      <TradingPanel data={data.trading_decision} />
      <div className="grid-2" style={{ marginTop: "1.5rem" }}>
        <NewsPanel data={data.news} />
        <FundamentalPanel data={data.fundamentals} />
      </div>
      <div style={{ marginTop: "1.5rem" }}>
        <RiskPanel data={data.risk_management} />
      </div>
    </div>
  );
}
