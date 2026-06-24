"use client";

import { useCallback, useEffect, useState } from "react";
import { getDashboard, getNewsAnalysis, getSymbols, SOURCE_LABELS } from "@/lib/api";
import type { DashboardData, NewsAnalysisResult } from "@/types";
import SignalPanel from "@/components/SignalPanel";
import MultiTimeframePanel from "@/components/MultiTimeframePanel";
import TradingViewWidget from "@/components/TradingViewWidget";
import OandaPanel from "@/components/OandaPanel";

function sentimentLabel(s: string) {
  if (s === "bullish") return "強気";
  if (s === "bearish") return "弱気";
  return "中立";
}

export default function IntegrationDashboard() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [data, setData] = useState<DashboardData | null>(null);
  const [news, setNews] = useState<NewsAnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dash, newsRes] = await Promise.all([
        getDashboard(symbol),
        getNewsAnalysis(symbol),
      ]);
      setData(dash);
      setNews(newsRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return <div className="loading">統合ダッシュボードを読み込み中...</div>;
  }

  if (error && !data) {
    return <div className="error-text">{error}</div>;
  }

  if (!data) return null;

  const bt = data.backtest_backtrader;
  const simple = data.backtest_simple;

  return (
    <>
      <div className="page-header">
        <h1>統合トレードダッシュボード</h1>
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
            更新
          </button>
        </div>
      </div>

      <p className="hint stack-note">
        {data.stack.api} + {data.stack.frontend} — {data.stack.note}
      </p>

      <div className="grid-2">
        <TradingViewWidget symbol={symbol} />
        <div>
          <SignalPanel signals={data.signals} price={data.price} symbol={data.symbol} />
          <MultiTimeframePanel symbol={symbol} />
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>TradingView Webhook シグナル</h2>
          {data.tradingview_signals.length === 0 ? (
            <p className="hint">
              受信シグナルなし。TradingView アラートの Webhook URL に{" "}
              <code>/api/tradingview/webhook</code> を設定してください。
            </p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>時刻</th>
                  <th>方向</th>
                  <th>価格</th>
                  <th>戦略</th>
                </tr>
              </thead>
              <tbody>
                {data.tradingview_signals.map((s) => (
                  <tr key={s.id}>
                    <td>
                      {s.received_at
                        ? new Date(s.received_at).toLocaleString("ja-JP")
                        : "—"}
                    </td>
                    <td className={s.action === "buy" ? "text-buy" : "text-sell"}>{s.action}</td>
                    <td>{s.price ?? "—"}</td>
                    <td>{s.strategy ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h2>ニュース分析（ML + OpenAI）</h2>
          {news && (
            <>
              <div className="stat-grid" style={{ marginBottom: "1rem" }}>
                <div className="stat-item">
                  <div className="label">ML センチメント</div>
                  <div className="value">{sentimentLabel(news.ml.sentiment)}</div>
                </div>
                <div className="stat-item">
                  <div className="label">ML スコア</div>
                  <div className="value">{news.ml.sentiment_score}</div>
                </div>
                {news.openai && (
                  <div className="stat-item">
                    <div className="label">OpenAI</div>
                    <div className="value">{sentimentLabel(news.openai.sentiment)}</div>
                  </div>
                )}
              </div>
              <p className="hint">{news.ml.summary}</p>
              {news.openai?.summary && <p>{news.openai.summary}</p>}
              {news.openai_error && (
                <p className="hint">OpenAI: {news.openai_error}</p>
              )}
              {!data.openai_configured && (
                <p className="hint">OPENAI_API_KEY 未設定 — ML キーワード分析のみ</p>
              )}
              <h3>最新ヘッドライン</h3>
              <ul className="headline-list">
                {news.articles.slice(0, 5).map((a, i) => (
                  <li key={i}>
                    <a href={a.url} target="_blank" rel="noreferrer">
                      {a.title}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Backtrader バックテスト</h2>
          {bt.status === "success" ? (
            <div className="stat-grid">
              <div className="stat-item">
                <div className="label">戦略</div>
                <div className="value" style={{ fontSize: "0.85rem" }}>
                  {bt.strategy}
                </div>
              </div>
              <div className="stat-item">
                <div className="label">初期資金</div>
                <div className="value">{bt.initial_cash?.toLocaleString()}</div>
              </div>
              <div className="stat-item">
                <div className="label">最終評価額</div>
                <div className="value">{bt.final_value?.toLocaleString()}</div>
              </div>
              <div className="stat-item">
                <div className="label">総リターン</div>
                <div
                  className="value"
                  style={{
                    color:
                      (bt.total_return_pct ?? 0) >= 0 ? "var(--buy)" : "var(--sell)",
                  }}
                >
                  {bt.total_return_pct}%
                </div>
              </div>
            </div>
          ) : (
            <p className="hint">{bt.message ?? "バックテスト失敗"}</p>
          )}
          <h3 style={{ marginTop: "1rem" }}>簡易シグナル BT（参考）</h3>
          <p className="hint">
            勝率 {simple.win_rate}% / 取引 {simple.total_trades} 回 / 平均{" "}
            {simple.avg_return_pct}%（{SOURCE_LABELS[simple.source ?? ""] ?? simple.source}）
          </p>
        </div>

        <OandaPanel
          status={data.oanda}
          orders={data.recent_orders}
          symbol={symbol}
          onOrderPlaced={load}
        />
      </div>
    </>
  );
}
