/**
 * @file IntegrationDashboard.tsx
 * @description 統合トレードダッシュボード — 全分析要素を 1 画面に集約したメイン画面
 *
 * 以下のコンポーネントとデータソースを統合して表示する：
 *   - TradingViewWidget     : リアルタイムの TradingView 埋め込みチャート
 *   - SignalPanel           : ルールベース売買シグナルと現在価格
 *   - MultiTimeframePanel   : マルチタイムフレームのトレンド方向サマリー
 *   - TradingView Webhook   : TradingView アラートから受信したシグナルのログテーブル
 *   - ニュース分析           : ML キーワード + OpenAI センチメント分析
 *   - Backtrader バックテスト: 戦略バックテスト結果（勝率・リターン）
 *   - OandaPanel            : OANDA 口座情報と注文フォーム
 *
 * データ取得: マウント時と symbol 変更時に getDashboard() + getNewsAnalysis() を
 * 並列フェッチしてパフォーマンスを最適化する。
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { getDashboard, getNewsAnalysis, getSymbols, SOURCE_LABELS } from "@/lib/api";
import type { DashboardData, NewsAnalysisResult } from "@/types";
import SignalPanel from "@/components/SignalPanel";
import MultiTimeframePanel from "@/components/MultiTimeframePanel";
import TradingViewWidget from "@/components/TradingViewWidget";
import OandaPanel from "@/components/OandaPanel";

/**
 * センチメント値（英語）を日本語ラベルに変換するユーティリティ関数
 *
 * @param s - "bullish" | "bearish" | その他
 * @returns 日本語ラベル（"強気" / "弱気" / "中立"）
 */
function sentimentLabel(s: string) {
  if (s === "bullish") return "強気";
  if (s === "bearish") return "弱気";
  return "中立";
}

/**
 * IntegrationDashboard
 *
 * FX トレード支援プラットフォームのメインダッシュボード。
 * 通貨ペアを選択すると全データを自動再取得し、
 * チャート・シグナル・ニュース・バックテスト・注文を 1 画面で確認できる。
 *
 * ## データフロー
 * 1. マウント時: getSymbols() でセレクトボックスを初期化
 * 2. symbol 変更時: load() を自動呼び出し → getDashboard + getNewsAnalysis を並列取得
 * 3. 注文約定後: OandaPanel から onOrderPlaced コールバックで load() を再呼び出し
 */
export default function IntegrationDashboard() {
  /** 通貨ペア一覧（セレクトボックス用）*/
  const [symbols, setSymbols] = useState<string[]>([]);
  /** 現在選択中の通貨ペア — デフォルト USDJPY */
  const [symbol, setSymbol] = useState("USDJPY");
  /** ダッシュボードのメインデータ（シグナル・バックテスト・OANDA 情報を含む） */
  const [data, setData] = useState<DashboardData | null>(null);
  /** ニュース分析結果（ML センチメント + OpenAI 要約 + 記事リスト） */
  const [news, setNews] = useState<NewsAnalysisResult | null>(null);
  /** API 呼び出し中フラグ — ボタン連打防止 */
  const [loading, setLoading] = useState(true);
  /** エラーメッセージ */
  const [error, setError] = useState<string | null>(null);

  /**
   * ダッシュボードデータとニュース分析を並列取得する関数
   * Promise.all で 2 つの API を同時に呼び出してレイテンシを削減する。
   * useCallback でメモ化し、symbol が変わるたびに新しいインスタンスを生成する。
   */
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // getDashboard（シグナル・バックテスト・OANDA）と getNewsAnalysis を並列取得
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

  /**
   * マウント時に通貨ペア一覧を取得する副作用
   * 依存配列が空なのでコンポーネント初期化時に 1 回のみ実行される
   */
  useEffect(() => {
    getSymbols().then((r) => setSymbols(r.symbols));
  }, []);

  /**
   * symbol が変化するたびにダッシュボードデータを再取得する副作用
   * load 関数が useCallback でメモ化されているため依存配列は [load] のみ
   */
  useEffect(() => {
    load();
  }, [load]);

  /** 初回ロード中かつデータ未取得の場合は全画面スピナーを表示 */
  if (loading && !data) {
    return <div className="loading">統合ダッシュボードを読み込み中...</div>;
  }

  /** データ取得失敗かつデータなしの場合はエラーテキストを表示 */
  if (error && !data) {
    return <div className="error-text">{error}</div>;
  }

  /** データが null の場合は何も表示しない（通常は発生しない） */
  if (!data) return null;

  /** Backtrader バックテスト結果（status === "success" かどうかで表示内容を分岐） */
  const bt = data.backtest_backtrader;
  /** 簡易シグナルバックテスト結果（勝率・取引数・平均リターン） */
  const simple = data.backtest_simple;

  return (
    <>
      <div className="page-header">
        <h1>統合トレードダッシュボード</h1>
        <div className="controls">
          {/* 通貨ペア選択セレクトボックス — 変更すると全データを自動再取得 */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          {/* 手動更新ボタン — API 呼び出し中は無効化 */}
          <button type="button" className="btn-secondary" onClick={load} disabled={loading}>
            更新
          </button>
        </div>
      </div>

      {/* テクノロジースタック情報バッジ（API + フロントエンドフレームワーク名） */}
      <p className="hint stack-note">
        {data.stack.api} + {data.stack.frontend} — {data.stack.note}
      </p>

      {/* === 上段: TradingView チャート（左）+ シグナル・MTF パネル（右） === */}
      <div className="grid-2">
        {/* TradingView 埋め込みウィジェット — リアルタイム価格チャート */}
        <TradingViewWidget symbol={symbol} />
        <div>
          {/* ルールベース売買シグナルと現在価格の表示 */}
          <SignalPanel signals={data.signals} price={data.price} symbol={data.symbol} />
          {/* マルチタイムフレーム（15M/1H/4H/1D）のトレンド方向サマリー */}
          <MultiTimeframePanel symbol={symbol} />
        </div>
      </div>

      {/* === 中段: TradingView Webhook シグナルログ（左）+ ニュース分析（右） === */}
      <div className="grid-2">
        <div className="card">
          <h2>TradingView Webhook シグナル</h2>
          {/* Webhook シグナルが 0 件の場合は設定方法を案内 */}
          {data.tradingview_signals.length === 0 ? (
            <p className="hint">
              受信シグナルなし。TradingView アラートの Webhook URL に{" "}
              <code>/api/tradingview/webhook</code> を設定してください。
            </p>
          ) : (
            // シグナルが存在する場合は受信ログテーブルを表示
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
                      {/* 受信時刻を日本語ロケールで表示、未設定の場合は「—」 */}
                      {s.received_at
                        ? new Date(s.received_at).toLocaleString("ja-JP")
                        : "—"}
                    </td>
                    {/* buy は緑、sell は赤でテキストカラーを切り替え */}
                    <td className={s.action === "buy" ? "text-buy" : "text-sell"}>{s.action}</td>
                    <td>{s.price ?? "—"}</td>
                    <td>{s.strategy ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ニュース分析カード: ML キーワード分析 + OpenAI 要約 + 記事ヘッドライン */}
        <div className="card">
          <h2>ニュース分析（ML + OpenAI）</h2>
          {/* news データが取得できている場合のみコンテンツを表示 */}
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
                {/* OpenAI によるセンチメントが存在する場合のみ追加表示 */}
                {news.openai && (
                  <div className="stat-item">
                    <div className="label">OpenAI</div>
                    <div className="value">{sentimentLabel(news.openai.sentiment)}</div>
                  </div>
                )}
              </div>
              <p className="hint">{news.ml.summary}</p>
              {/* OpenAI 要約が存在する場合のみ詳細テキストを表示 */}
              {news.openai?.summary && <p>{news.openai.summary}</p>}
              {/* OpenAI API エラーが発生した場合のエラーメッセージ（API キー未設定等） */}
              {news.openai_error && (
                <p className="hint">OpenAI: {news.openai_error}</p>
              )}
              {/* OPENAI_API_KEY が未設定の場合はMLのみであることを案内 */}
              {!data.openai_configured && (
                <p className="hint">OPENAI_API_KEY 未設定 — ML キーワード分析のみ</p>
              )}
              {/* 最新 5 件のニュース記事ヘッドライン（外部リンク） */}
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

      {/* === 下段: バックテスト結果（左）+ OANDA 注文パネル（右） === */}
      <div className="grid-2">
        {/* Backtrader バックテスト + 簡易シグナルバックテストのサマリーカード */}
        <div className="card">
          <h2>Backtrader バックテスト</h2>
          {/* Backtrader が成功した場合のみ詳細統計を表示、失敗時はメッセージを表示 */}
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
                {/* 総リターンがプラスなら買い色、マイナスなら売り色 */}
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
          {/* 簡易シグナルバックテストのサマリー（勝率・取引数・平均リターン） */}
          <h3 style={{ marginTop: "1rem" }}>簡易シグナル BT（参考）</h3>
          <p className="hint">
            勝率 {simple.win_rate}% / 取引 {simple.total_trades} 回 / 平均{" "}
            {simple.avg_return_pct}%（{SOURCE_LABELS[simple.source ?? ""] ?? simple.source}）
          </p>
        </div>

        {/*
         * OANDA パネル: 口座残高・保有ポジション・注文フォームを表示する子コンポーネント。
         * onOrderPlaced コールバックで注文約定後に load() を呼び出してデータを再取得する。
         */}
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
