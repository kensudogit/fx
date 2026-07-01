/**
 * @file AIProDashboard.tsx
 * @description AI Pro ダッシュボード — プレミアム差別化機能画面
 *
 * 本コンポーネントは「AI Pro」プランのコア画面を提供する。
 * 以下の 7 タブで構成され、タブ切り替えごとに対応する API を呼び出す：
 *   - AIシグナル    : ルールベース + ML を統合した売買シグナル
 *   - 市場ブリーフ  : ニュース・SNS・経済指標の要約
 *   - AIコーチング  : トレード改善提案（OpenAI ベース）
 *   - バックテスト  : 簡易 / Backtrader / ウォークフォワードの 3 種
 *   - リスク管理    : 最大 DD・推奨ロット・資金配分
 *   - 口座・通貨    : マルチアカウント一元管理
 *   - AIチャット    : セッション維持型の投資相談チャット
 */

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

/** タブ識別子の型。7 つのサブ機能を切り替える */
type ProTab =
  | "signals"
  | "brief"
  | "coaching"
  | "backtest"
  | "risk"
  | "portfolio"
  | "chat";

/** API が返す英語アクション名を日本語ラベルに変換するマップ */
const ACTION_LABEL: Record<string, string> = { buy: "買い", sell: "売り", hold: "様子見" };

/**
 * AIProDashboard
 *
 * AI Pro プランのメインダッシュボード。
 * 通貨ペア選択・タブ切り替えに応じてバックエンドの Pro API エンドポイントを呼び出し、
 * 各分析結果をカードレイアウトで表示する。
 * チャットタブのみ独自のメッセージ管理（セッション ID を保持）を行う。
 */
export default function AIProDashboard() {
  /** 通貨ペア一覧（セレクトボックス用）— 初期値は空配列 */
  const [symbols, setSymbols] = useState<string[]>([]);
  /** 現在選択中の通貨ペア — デフォルト USDJPY */
  const [symbol, setSymbol] = useState("USDJPY");
  /** アクティブなタブ — デフォルトは signals（AIシグナル） */
  const [tab, setTab] = useState<ProTab>("signals");
  /** API 呼び出し中フラグ — ボタン二重押し防止に使用 */
  const [loading, setLoading] = useState(false);
  /** エラーメッセージ — null の場合は非表示 */
  const [error, setError] = useState<string | null>(null);
  /** リスク管理タブで使用する口座残高（USD）— デフォルト 10000 */
  const [balance, setBalance] = useState(10000);

  /** AIシグナルタブの結果データ */
  const [signals, setSignals] = useState<AISignalResult | null>(null);
  /** 市場ブリーフタブの結果データ */
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  /** AIコーチングタブの結果データ */
  const [coaching, setCoaching] = useState<CoachingResult | null>(null);
  /**
   * バックテストタブの結果データ
   * - simple      : 簡易シグナルバックテスト
   * - backtrader  : Backtrader エンジンによる詳細バックテスト
   * - walk_forward: ウォークフォワード分析（過学習検証）
   */
  const [backtest, setBacktest] = useState<{
    simple: SignalBacktest;
    backtrader: BacktraderResult;
    walk_forward: WalkForwardResult;
  } | null>(null);
  /** リスク管理タブの結果データ */
  const [risk, setRisk] = useState<AdvancedRisk | null>(null);
  /** ポートフォリオタブの結果データ */
  const [portfolio, setPortfolio] = useState<PortfolioOverview | null>(null);

  /** チャット入力欄の現在テキスト */
  const [chatInput, setChatInput] = useState("");
  /** チャットメッセージ履歴（user / assistant 交互） */
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  /** チャットセッション ID — 会話コンテキスト維持に使用（初回は undefined） */
  const [sessionId, setSessionId] = useState<number | undefined>();
  /** チャット末尾スクロール用の参照 — メッセージ追加時に自動スクロール */
  const chatEndRef = useRef<HTMLDivElement>(null);

  /**
   * マウント時に通貨ペア一覧を取得する副作用
   * 依存配列が空のためコンポーネント初期化時に 1 回のみ実行される
   */
  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  /**
   * 現在のタブ・通貨ペア・残高に応じてデータを取得する関数
   * useCallback でメモ化し、依存変数（tab / symbol / balance）が変わったときだけ再生成する
   */
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // タブに応じて対応する API エンドポイントを呼び出す
      if (tab === "signals") setSignals(await getProSignals(symbol));
      else if (tab === "brief") setBrief(await getProMarketBrief(symbol));
      else if (tab === "coaching") setCoaching(await getProCoaching(symbol));
      else if (tab === "backtest") setBacktest(await getProBacktest(symbol));
      // リスク管理は口座残高も送信してポジションサイズ計算に利用する
      else if (tab === "risk") setRisk(await getProRisk(symbol, balance));
      // ポートフォリオは通貨ペア非依存で全口座情報を取得する
      else if (tab === "portfolio") setPortfolio(await getProPortfolio());
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [tab, symbol, balance]);

  /**
   * tab / symbol / balance が変化するたびにデータを自動ロードする副作用
   * チャットタブは独自の送受信フローを持つため load() をスキップする
   */
  useEffect(() => {
    if (tab !== "chat") load();
  }, [load, tab]);

  /**
   * チャットメッセージを送信する非同期ハンドラ
   * - 入力欄をクリアしてからユーザーメッセージを楽観的に追加する
   * - セッション ID を維持して会話コンテキストをサーバー側に引き継ぐ
   * - レスポンスが messages（履歴全体）を含む場合はそちらで置換する
   */
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const msg = chatInput.trim();
    setChatInput("");
    // ユーザーメッセージを即座に表示（楽観的 UI）
    setChatMessages((m) => [...m, { role: "user", content: msg }]);
    setLoading(true);
    try {
      const res = await sendProChat(msg, symbol, sessionId);
      // サーバーがセッション ID を返した場合は保存して次回送信時に渡す
      if (res.session_id) setSessionId(res.session_id);
      // messages フィールドがある場合は履歴全体を置換、ない場合は追記
      if (res.messages) setChatMessages(res.messages);
      else setChatMessages((m) => [...m, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "チャットエラー");
    } finally {
      setLoading(false);
    }
  };

  /**
   * チャットメッセージが更新されるたびに末尾へスムーズスクロールする副作用
   * chatEndRef が指す空 div を目標としてスクロールする
   */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  /** タブ定義配列 — key（内部識別子）と label（表示ラベル）のペア */
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
          {/* 通貨ペア選択セレクトボックス */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          {/* リスクタブのみ口座残高入力を表示（ポジションサイズ計算に必要） */}
          {(tab === "risk") && (
            <input
              type="number"
              value={balance}
              onChange={(e) => setBalance(Number(e.target.value))}
              className="balance-input"
              placeholder="残高"
            />
          )}
          {/* チャットタブは独自送信ボタンを使うため「実行」ボタンを非表示 */}
          {tab !== "chat" && (
            <button type="button" className="btn" onClick={load} disabled={loading}>
              {loading ? "分析中..." : "実行"}
            </button>
          )}
        </div>
      </div>

      {/* タブナビゲーション — クリックで tab state を更新 */}
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

      {/* エラー発生時のバナー表示 */}
      {error && <div className="error-banner">{error}</div>}

      {/* === AIシグナルタブ: signals データが取得済みの場合のみ表示 === */}
      {tab === "signals" && signals && (
        <div className="card">
          <h2>
            AI売買シグナル — {signals.symbol}{" "}
            {/* アクション（buy/sell/hold）に応じたバッジカラーを切り替え */}
            <span className={`badge badge-${signals.action === "buy" ? "buy" : signals.action === "sell" ? "sell" : "neutral"}`}>
              {ACTION_LABEL[signals.action]} {signals.confidence}%
            </span>
          </h2>
          <p>{signals.summary}</p>
          <p className="hint">価格: {signals.price}</p>
          {/* ルールベース各インジケータのシグナル一覧 */}
          {signals.rule_signals.map((s, i) => (
            <div key={i} className={s.signal === "buy" ? "signal-buy" : "signal-sell"}>
              <strong>{s.indicator}</strong> — {s.reason}
            </div>
          ))}
        </div>
      )}

      {/* === 市場ブリーフタブ: OpenAI 要約・ニュース・SNS・経済指標を表示 === */}
      {tab === "brief" && brief && (
        <div className="card">
          <h2>市場ブリーフ — {brief.symbol}</h2>
          {/* OpenAI のエグゼクティブサマリー（存在する場合のみ表示） */}
          {brief.openai?.executive_summary && <p>{brief.openai.executive_summary}</p>}
          {/* トレードへの示唆（存在する場合のみ表示） */}
          {brief.openai?.trading_implication && (
            <p className="hint"><strong>示唆:</strong> {brief.openai.trading_implication}</p>
          )}
          <h3>ニュース ({brief.news.ml.sentiment})</h3>
          {/* 最新 5 件のニュース記事タイトル */}
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

      {/* === AIコーチングタブ: 総合評価・改善提案・次の焦点を表示 === */}
      {tab === "coaching" && coaching && (
        <div className="card">
          <h2>AIコーチング — {coaching.symbol}</h2>
          {/* 全体評価（存在する場合のみ表示） */}
          {coaching.coaching?.overall_assessment && <p>{coaching.coaching.overall_assessment}</p>}
          {/* 改善提案リスト（存在する場合のみ表示） */}
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
          {/* 次に注力すべきポイント（存在する場合のみ表示） */}
          {coaching.coaching?.next_focus && (
            <p className="hint"><strong>次の焦点:</strong> {coaching.coaching.next_focus}</p>
          )}
        </div>
      )}

      {/* === バックテストタブ: 3 種のバックテスト結果を 2 カラムグリッドで表示 === */}
      {tab === "backtest" && backtest && (
        <div className="grid-2">
          {/* 簡易バックテスト: 勝率と取引回数のみ表示 */}
          <div className="card">
            <h2>簡易バックテスト</h2>
            <p>勝率 {backtest.simple.win_rate}% / 取引 {backtest.simple.total_trades}回</p>
          </div>
          {/* Backtrader バックテスト: 成功時はリターン率、失敗時はエラーメッセージ */}
          <div className="card">
            <h2>Backtrader</h2>
            {backtest.backtrader.status === "success" ? (
              <p>リターン {backtest.backtrader.total_return_pct}%</p>
            ) : (
              <p>{backtest.backtrader.message}</p>
            )}
          </div>
          {/* ウォークフォワード: 2 列全幅で表示。サンプル内/外の勝率比較で過学習を検証 */}
          <div className="card" style={{ gridColumn: "1 / -1" }}>
            <h2>ウォークフォワード</h2>
            {/* status === "success" かつ summary が存在する場合のみ詳細を表示 */}
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

      {/* === リスク管理タブ: 最大DD・推奨ロット・SL/TP・資金配分テーブルを表示 === */}
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
          {/* ボラティリティ逆数加重による通貨ペアへの資金配分テーブル */}
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

      {/* === ポートフォリオタブ: 全口座・全通貨ペアの一覧テーブルを表示 === */}
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
                  {/* 30 日変化がプラスなら買い色、マイナスなら売り色で表示 */}
                  <td className={p.change_30d_pct >= 0 ? "text-buy" : "text-sell"}>{p.change_30d_pct}%</td>
                  <td>{p.open_orders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* === チャットタブ: セッション維持型の AI 投資相談インターフェース === */}
      {tab === "chat" && (
        <div className="card chat-panel">
          <h2>AI投資相談 — {symbol}</h2>
          <div className="chat-messages">
            {/* メッセージが 0 件のときはガイダンステキストを表示 */}
            {chatMessages.length === 0 && (
              <p className="hint">FX・リスク・テクニカルについて自由に質問してください。</p>
            )}
            {/* チャットメッセージを role（user / assistant）でスタイルを切り替え */}
            {chatMessages.map((m, i) => (
              <div key={i} className={`chat-bubble chat-${m.role}`}>
                <strong>{m.role === "user" ? "あなた" : "AI"}</strong>
                <p>{m.content}</p>
              </div>
            ))}
            {/* 末尾スクロール用のアンカー要素 */}
            <div ref={chatEndRef} />
          </div>
          <div className="chat-input-row">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              {/* Enter キー（Shift 非押下）で sendChat を呼び出す */}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendChat()}
              placeholder="例: USDJPYの今週の戦略を教えて"
            />
            <button type="button" className="btn" onClick={sendChat} disabled={loading}>
              送信
            </button>
          </div>
        </div>
      )}

      {/* チャットタブ以外のローディングインジケータ */}
      {loading && tab !== "chat" && <div className="loading">処理中...</div>}
    </>
  );
}
