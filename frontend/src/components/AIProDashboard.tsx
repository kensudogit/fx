"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSymbols,
  getProSignals,
  getProMarketBrief,
  getProCoaching,
  getProBacktest,
  getProRisk,
  getProPortfolio,
  sendProChat,
} from "@/lib/api";
import type {
  AISignalResult,
  MarketBrief,
  CoachingResult,
  AdvancedRisk,
  PortfolioOverview,
  ChatMessage,
  WalkForwardResult,
  BacktraderResult,
  SignalBacktest,
} from "@/types";

type ProTab =
  | "signals"
  | "brief"
  | "coaching"
  | "backtest"
  | "risk"
  | "portfolio"
  | "chat";

const ACTION_LABEL: Record<string, string> = { buy: "買い", sell: "売り", hold: "様子見" };

export default function AIProDashboard() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symbol, setSymbol] = useState("USDJPY");
  const [tab, setTab] = useState<ProTab>("signals");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [balance, setBalance] = useState(10000);

  const [signals, setSignals] = useState<AISignalResult | null>(null);
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [coaching, setCoaching] = useState<CoachingResult | null>(null);
  const [backtest, setBacktest] = useState<{
    simple: SignalBacktest;
    backtrader: BacktraderResult;
    walk_forward: WalkForwardResult;
  } | null>(null);
  const [risk, setRisk] = useState<AdvancedRisk | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioOverview | null>(null);

  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<number | undefined>();
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === "signals") setSignals(await getProSignals(symbol));
      else if (tab === "brief") setBrief(await getProMarketBrief(symbol));
      else if (tab === "coaching") setCoaching(await getProCoaching(symbol));
      else if (tab === "backtest") setBacktest(await getProBacktest(symbol));
      else if (tab === "risk") setRisk(await getProRisk(symbol, balance));
      else if (tab === "portfolio") setPortfolio(await getProPortfolio());
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [tab, symbol, balance]);

  useEffect(() => {
    if (tab !== "chat") load();
  }, [load, tab]);

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput("");
    setChatMessages((m) => [...m, { role: "user", content: msg }]);
    setLoading(true);
    try {
      const res = await sendProChat(msg, symbol, sessionId);
      if (res.session_id) setSessionId(res.session_id);
      if (res.messages) setChatMessages(res.messages);
      else setChatMessages((m) => [...m, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "チャットエラー");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const tabs: { key: ProTab; label: string }[] = [
    { key: "signals", label: "AIシグナル" },
    { key: "brief", label: "市場ブリーフ" },
    { key: "coaching", label: "AIコーチング" },
    { key: "backtest", label: "バックテスト" },
    { key: "risk", label: "リスク管理" },
    { key: "portfolio", label: "口座・通貨" },
    { key: "chat", label: "AIチャット" },
  ];

  return (
    <>
      <div className="page-header">
        <h1>AI Pro — 差別化機能</h1>
        <div className="controls">
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          {(tab === "risk") && (
            <input
              type="number"
              value={balance}
              onChange={(e) => setBalance(Number(e.target.value))}
              className="balance-input"
              placeholder="残高"
            />
          )}
          {tab !== "chat" && (
            <button type="button" className="btn" onClick={load} disabled={loading}>
              {loading ? "分析中..." : "実行"}
            </button>
          )}
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

      {tab === "signals" && signals && (
        <div className="card">
          <h2>
            AI売買シグナル — {signals.symbol}{" "}
            <span className={`badge badge-${signals.action === "buy" ? "buy" : signals.action === "sell" ? "sell" : "neutral"}`}>
              {ACTION_LABEL[signals.action]} {signals.confidence}%
            </span>
          </h2>
          <p>{signals.summary}</p>
          <p className="hint">価格: {signals.price}</p>
          {signals.rule_signals.map((s, i) => (
            <div key={i} className={s.signal === "buy" ? "signal-buy" : "signal-sell"}>
              <strong>{s.indicator}</strong> — {s.reason}
            </div>
          ))}
        </div>
      )}

      {tab === "brief" && brief && (
        <div className="card">
          <h2>市場ブリーフ — {brief.symbol}</h2>
          {brief.openai?.executive_summary && <p>{brief.openai.executive_summary}</p>}
          {brief.openai?.trading_implication && (
            <p className="hint"><strong>示唆:</strong> {brief.openai.trading_implication}</p>
          )}
          <h3>ニュース ({brief.news.ml.sentiment})</h3>
          <ul className="headline-list">
            {brief.news.articles.slice(0, 5).map((a, i) => (
              <li key={i}>{a.title}</li>
            ))}
          </ul>
          <h3>SNS</h3>
          <p>{brief.sns.summary}</p>
          <h3>経済指標</h3>
          <p>{brief.economic.overview}</p>
        </div>
      )}

      {tab === "coaching" && coaching && (
        <div className="card">
          <h2>AIコーチング — {coaching.symbol}</h2>
          {coaching.coaching?.overall_assessment && <p>{coaching.coaching.overall_assessment}</p>}
          {coaching.coaching?.recommendations && (
            <>
              <h3>改善提案</h3>
              <ul className="headline-list">
                {coaching.coaching.recommendations.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          )}
          {coaching.coaching?.next_focus && (
            <p className="hint"><strong>次の焦点:</strong> {coaching.coaching.next_focus}</p>
          )}
        </div>
      )}

      {tab === "backtest" && backtest && (
        <div className="grid-2">
          <div className="card">
            <h2>簡易バックテスト</h2>
            <p>勝率 {backtest.simple.win_rate}% / 取引 {backtest.simple.total_trades}回</p>
          </div>
          <div className="card">
            <h2>Backtrader</h2>
            {backtest.backtrader.status === "success" ? (
              <p>リターン {backtest.backtrader.total_return_pct}%</p>
            ) : (
              <p>{backtest.backtrader.message}</p>
            )}
          </div>
          <div className="card" style={{ gridColumn: "1 / -1" }}>
            <h2>ウォークフォワード</h2>
            {backtest.walk_forward.status === "success" && backtest.walk_forward.summary ? (
              <>
                <p>{backtest.walk_forward.summary.robustness_label}</p>
                <p className="hint">
                  IS勝率 {backtest.walk_forward.summary.avg_in_sample_win_rate}% →
                  OOS {backtest.walk_forward.summary.avg_out_of_sample_win_rate}%
                  （{backtest.walk_forward.summary.window_count}ウィンドウ）
                </p>
              </>
            ) : (
              <p>{backtest.walk_forward.message ?? "データ不足"}</p>
            )}
          </div>
        </div>
      )}

      {tab === "risk" && risk && (
        <div className="card">
          <h2>リスク管理 — {risk.symbol}</h2>
          <div className="stat-grid">
            <div className="stat-item">
              <div className="label">最大DD</div>
              <div className="value">{risk.drawdown.max_drawdown_pct}%</div>
            </div>
            <div className="stat-item">
              <div className="label">推奨ロット</div>
              <div className="value">{risk.position_sizing.recommended_lots}</div>
            </div>
            <div className="stat-item">
              <div className="label">損切り</div>
              <div className="value">{risk.stop_loss.price}</div>
            </div>
            <div className="stat-item">
              <div className="label">利確</div>
              <div className="value">{risk.take_profit.price}</div>
            </div>
          </div>
          <h3>資金配分（ボラ逆数）</h3>
          <table className="data-table">
            <thead><tr><th>通貨</th><th>ウェイト</th><th>配分USD</th></tr></thead>
            <tbody>
              {risk.capital_allocation.pairs.map((p) => (
                <tr key={p.symbol}><td>{p.symbol}</td><td>{p.weight_pct}%</td><td>{p.allocated_usd}</td></tr>
              ))}
            </tbody>
          </table>
          <ul className="headline-list">
            {risk.recommendations.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {tab === "portfolio" && portfolio && (
        <div className="card">
          <h2>口座・通貨ペア一元管理</h2>
          <p>{portfolio.summary}</p>
          <p>総残高: {portfolio.total_balance.toLocaleString()} USD</p>
          <h3>口座</h3>
          <table className="data-table">
            <thead><tr><th>名前</th><th>ブローカー</th><th>残高</th></tr></thead>
            <tbody>
              {portfolio.accounts.map((a) => (
                <tr key={a.id}><td>{a.name}</td><td>{a.broker}</td><td>{a.balance}</td></tr>
              ))}
            </tbody>
          </table>
          <h3>通貨ペア</h3>
          <table className="data-table">
            <thead><tr><th>通貨</th><th>価格</th><th>30日変化</th><th>注文数</th></tr></thead>
            <tbody>
              {portfolio.pairs.map((p) => (
                <tr key={p.symbol}>
                  <td>{p.symbol}</td><td>{p.price}</td>
                  <td className={p.change_30d_pct >= 0 ? "text-buy" : "text-sell"}>{p.change_30d_pct}%</td>
                  <td>{p.open_orders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "chat" && (
        <div className="card chat-panel">
          <h2>AI投資相談 — {symbol}</h2>
          <div className="chat-messages">
            {chatMessages.length === 0 && (
              <p className="hint">FX・リスク・テクニカルについて自由に質問してください。</p>
            )}
            {chatMessages.map((m, i) => (
              <div key={i} className={`chat-bubble chat-${m.role}`}>
                <strong>{m.role === "user" ? "あなた" : "AI"}</strong>
                <p>{m.content}</p>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          <div className="chat-input-row">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendChat()}
              placeholder="例: USDJPYの今週の戦略を教えて"
            />
            <button type="button" className="btn" onClick={sendChat} disabled={loading}>
              送信
            </button>
          </div>
        </div>
      )}

      {loading && tab !== "chat" && <div className="loading">処理中...</div>}
    </>
  );
}
