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
} from "@/lib/api";
import type {
  IntelligenceReport,
  TrendPrediction,
  NewsAnalysisResult,
  SNSAnalysis,
  EconomicAnalysis,
  VolatilityPrediction,
} from "@/types";

type AnalysisTab = "overview" | "trend" | "news" | "sns" | "economic" | "volatility";

const SENTIMENT: Record<string, string> = {
  bullish: "強気",
  bearish: "弱気",
  neutral: "中立",
};

const IMPACT: Record<string, string> = {
  positive: "ポジティブ",
  negative: "ネガティブ",
  neutral: "中立",
};

function BiasBadge({ value }: { value: string }) {
  const cls = value === "bullish" ? "badge-buy" : value === "bearish" ? "badge-sell" : "badge-neutral";
  return <span className={`badge ${cls}`}>{SENTIMENT[value] ?? value}</span>;
}

export default function AnalysisDashboard() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [tab, setTab] = useState<AnalysisTab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [report, setReport] = useState<IntelligenceReport | null>(null);
  const [trend, setTrend] = useState<TrendPrediction | null>(null);
  const [news, setNews] = useState<NewsAnalysisResult | null>(null);
  const [sns, setSns] = useState<SNSAnalysis | null>(null);
  const [economic, setEconomic] = useState<EconomicAnalysis | null>(null);
  const [volatility, setVolatility] = useState<VolatilityPrediction | null>(null);

  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "overview") {
        setReport(await getIntelligenceReport(symbol));
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
  }, [symbol, tab]);

  useEffect(() => {
    load();
  }, [load]);

  const tabs: { key: AnalysisTab; label: string }[] = [
    { key: "overview", label: "総合" },
    { key: "trend", label: "トレンド予測" },
    { key: "news", label: "ニュース分析" },
    { key: "sns", label: "SNS分析" },
    { key: "economic", label: "経済指標" },
    { key: "volatility", label: "ボラ予測" },
  ];

  return (
    <>
      <div className="page-header">
        <h1>マーケット分析</h1>
        <div className="controls">
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            {loading ? "分析中..." : "再分析"}
          </button>
        </div>
      </div>

      <div className="tab-bar">
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
      {loading && !report && !trend && !news && !sns && !economic && !volatility && (
        <div className="loading">分析を実行中...</div>
      )}

      {tab === "overview" && report && (
        <div className="analysis-overview">
          <div className="card composite-card">
            <h2>{report.outlook_label}</h2>
            <div className="composite-score" data-sign={Math.sign(report.composite_score)}>
              {report.composite_score > 0 ? "+" : ""}
              {report.composite_score}
            </div>
            <p className="hint">トレンド・ニュース・SNS・経済指標・ボラを統合したスコア（-100〜100）</p>
          </div>
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
            <SummaryCard
              title="ボラティリティ"
              bias={report.volatility.forecast.regime === "high" ? "bearish" : "neutral"}
              detail={report.volatility.interpretation}
            />
          </div>
        </div>
      )}

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
          {trend.ml.status === "success" && (
            <p className="hint">
              ML ({trend.ml.model}): {SENTIMENT[trend.ml.trend ?? "neutral"]} / テスト精度{" "}
              {trend.ml.test_accuracy}%
            </p>
          )}
        </div>
      )}

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
            {news.openai && (
              <Stat label="OpenAI" value={SENTIMENT[news.openai.sentiment]} />
            )}
          </div>
          <p>{news.ml.summary}</p>
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

      {tab === "volatility" && volatility && (
        <div className="card">
          <h2>ボラティリティ予測 — {volatility.symbol}</h2>
          <p>{volatility.interpretation}</p>
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

function SummaryCard({
  title,
  bias,
  detail,
}: {
  title: string;
  bias: string;
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

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-item">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
