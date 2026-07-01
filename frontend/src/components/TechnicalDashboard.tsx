/**
 * @file TechnicalDashboard.tsx
 * @description テクニカル分析ダッシュボード（メインページ）
 *
 * FX トレード支援プラットフォームのテクニカル分析メイン画面。
 * 以下の機能を一画面に統合する：
 * - 通貨ペア・期間の選択コントロール
 * - リアルタイム価格（WebSocket）/ 終値の表示
 * - RSI・MACD などの最新指標値サマリー
 * - ML 予測価格と R² スコア
 * - タブ切り替え式チャート（価格/MA・BB・一目・RSI・MACD・ストキャス）
 * - トレードシグナルパネル
 * - マルチタイムフレームパネル
 * - ポジションサイズ計算パネル
 * - バックテストパネル
 * - 経済指標アラートバナー
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getTechnicalAnalysis,
  getTradingSignals,
  getMLPrediction,
  getSymbols,
  syncMarketData,
  openChartImage,
  SOURCE_LABELS,
} from "@/lib/api";
import type { TechnicalAnalysis, TradingSignal, MLPrediction } from "@/types";
import PriceChart, { OscillatorChart } from "@/components/Chart";
import SignalPanel from "@/components/SignalPanel";
import MultiTimeframePanel from "@/components/MultiTimeframePanel";
import PositionSizePanel from "@/components/PositionSizePanel";
import BacktestPanel from "@/components/BacktestPanel";
import EventAlertBanner from "@/components/EventAlertBanner";
import { useLivePrices } from "@/lib/useLivePrices";

/**
 * チャートタブの種類を表す型。
 * - price     : 価格ローソク足 + 移動平均線
 * - bb        : ボリンジャーバンド
 * - ichimoku  : 一目均衡表
 * - rsi       : RSI オシレーター
 * - macd      : MACD オシレーター
 * - stochastic: ストキャスティクスオシレーター
 */
type IndicatorTab = "price" | "bb" | "ichimoku" | "rsi" | "macd" | "stochastic";

/**
 * データ取得期間の選択肢（日数）。
 * - 90日  : 短期トレンド確認向け
 * - 200日 : デフォルト、中期トレンド確認向け
 * - 365日 : 長期トレンド・年間サイクル確認向け
 */
const DAY_OPTIONS = [90, 200, 365];

/**
 * TechnicalDashboard
 *
 * テクニカル分析ページの全体レイアウトを管理するルートコンポーネント。
 * 通貨ペアや期間の選択に応じて複数の API を並列取得し、
 * 子コンポーネントへデータを配布する。
 *
 * ### データ取得フロー
 * 1. マウント時に `getSymbols()` で利用可能な通貨ペア一覧を取得
 * 2. symbol / days が変化するたびに `loadData()` で以下を並列取得:
 *    - テクニカル分析データ（`getTechnicalAnalysis`）
 *    - トレードシグナル（`getTradingSignals`）
 *    - ML 予測結果（`getMLPrediction`）
 * 3. WebSocket（`useLivePrices`）でリアルタイム価格を受信し、
 *    取得完了後（`!loading`）から接続を開始する
 */
export default function TechnicalDashboard() {
  /**
   * 選択可能な通貨ペアの一覧。
   * マウント時に API から取得する。初期値 []: 取得前は空配列
   */
  const [symbols, setSymbols] = useState<string[]>([]);

  /**
   * 現在選択中の通貨ペア。
   * 初期値 "USDJPY": 最も取引量の多いペアをデフォルトに設定
   */
  const [symbol, setSymbol] = useState("USDJPY");

  /**
   * データ取得日数。
   * 初期値 200: 中期分析のデフォルト値
   */
  const [days, setDays] = useState(200);

  /**
   * テクニカル分析データ（ローソク足・各種指標の時系列データ）。
   * 初期値 null: 取得前または取得失敗
   */
  const [data, setData] = useState<TechnicalAnalysis | null>(null);

  /**
   * トレードシグナルの配列。
   * 初期値 []: シグナルなし
   */
  const [signals, setSignals] = useState<TradingSignal[]>([]);

  /**
   * シグナル取得時の現在価格。
   * 初期値 0
   */
  const [price, setPrice] = useState(0);

  /**
   * ML モデルによる価格予測結果。
   * 初期値 null: 取得前または取得失敗
   */
  const [prediction, setPrediction] = useState<MLPrediction | null>(null);

  /**
   * アクティブなチャートタブ。
   * 初期値 "price": デフォルトは価格チャート（ローソク足 + MA）
   */
  const [activeTab, setActiveTab] = useState<IndicatorTab>("price");

  /**
   * データ取得中フラグ。
   * 初期値 true: 初回ロード中として扱う
   */
  const [loading, setLoading] = useState(true);

  /**
   * マーケットデータ同期処理中フラグ。
   * 初期値 false
   */
  const [syncing, setSyncing] = useState(false);

  /**
   * チャート画像取得中フラグ。
   * 初期値 false
   */
  const [openingChart, setOpeningChart] = useState(false);

  /**
   * エラーメッセージ。
   * 初期値 null: エラーなし
   */
  const [error, setError] = useState<string | null>(null);

  /**
   * WebSocket リアルタイム価格フック。
   * - `[symbol]`: 購読する通貨ペアのリスト（現在選択中の1ペアのみ）
   * - `!loading`: ローディング完了後に WebSocket 接続を開始する
   *   （テクニカルデータ取得が完了するまで接続しないことでリソースを節約）
   */
  const { quotes, connected } = useLivePrices([symbol], !loading);
  // 現在のシンボルのリアルタイム価格クオートを取得
  const liveQuote = quotes[symbol];

  /**
   * テクニカル分析・シグナル・ML 予測を並列取得する関数。
   * useCallback でメモ化し、symbol または days が変わった時のみ再生成する。
   * Promise.all で 3 つの API リクエストを並列実行して待機時間を最小化する。
   */
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // テクニカル分析・シグナル・ML予測を並列取得（直列より高速）
      const [tech, sig, pred] = await Promise.all([
        getTechnicalAnalysis(symbol, days),
        getTradingSignals(symbol, days),
        getMLPrediction(symbol, days),
      ]);
      setData(tech);
      setSignals(sig.signals);
      setPrice(sig.price);
      setPrediction(pred);
    } catch (e) {
      setError(e instanceof Error ? e.message : "データ取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, [symbol, days]);  // symbol または days が変わると loadData が再生成される

  /**
   * マウント時に通貨ペア一覧を取得する副作用。
   * 依存配列: [] — マウント時に一度だけ実行
   */
  useEffect(() => {
    getSymbols().then((res) => setSymbols(res.symbols));
  }, []);

  /**
   * loadData 関数が変わるたびにデータを再取得する副作用。
   * symbol または days の変更 → loadData が再生成 → このエフェクトが再実行される。
   * 依存配列: [loadData]
   */
  useEffect(() => {
    loadData();
  }, [loadData]);

  /**
   * マーケットデータの手動同期処理。
   * バックエンドにデータ同期リクエストを送り、完了後に画面を再読み込みする。
   */
  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    try {
      // バックエンドでデータソースから最新の OHLCV データを同期
      await syncMarketData(symbol, days);
      // 同期完了後にダッシュボードデータを再取得して反映
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "同期に失敗しました");
    } finally {
      setSyncing(false);
    }
  };

  /**
   * チャート画像（PNG）をバックエンドから取得してブラウザで開く処理。
   * matplotlib で生成されたチャート画像を新しいタブで表示する。
   */
  const handleOpenChart = async () => {
    setOpeningChart(true);
    setError(null);
    try {
      await openChartImage(symbol, days);
    } catch (e) {
      setError(e instanceof Error ? e.message : "チャート画像の取得に失敗しました");
    } finally {
      setOpeningChart(false);
    }
  };

  // 初回ローディング中（データ未取得）はローディング表示
  if (loading && !data) {
    return <div className="loading">データを読み込み中...</div>;
  }

  /**
   * チャートタブの定義リスト。
   * PriceChart と OscillatorChart コンポーネントに対応するタブを定義。
   */
  const tabs: { key: IndicatorTab; label: string }[] = [
    { key: "price", label: "価格 + MA" },
    { key: "bb", label: "ボリンジャーバンド" },
    { key: "ichimoku", label: "一目均衡表" },
    { key: "rsi", label: "RSI" },
    { key: "macd", label: "MACD" },
    { key: "stochastic", label: "ストキャスティクス" },
  ];

  return (
    <>
      {/* 経済指標イベントアラートバナー（重要指標発表前などに表示） */}
      <EventAlertBanner />

      {/* ページヘッダー: タイトルと操作コントロール */}
      <div className="page-header">
        <h1>テクニカル分析</h1>
        <div className="controls">
          {/* 通貨ペア選択セレクトボックス */}
          <div className="select-wrapper">
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          {/* 期間選択セレクトボックス（90/200/365日） */}
          <div className="select-wrapper">
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {DAY_OPTIONS.map((d) => (
                <option key={d} value={d}>{d}日</option>
              ))}
            </select>
          </div>
          {/* データ同期ボタン: 同期中はラベルを変更してフィードバック */}
          <button className="btn" onClick={handleSync} disabled={syncing}>
            {syncing ? "同期中..." : "データ同期"}
          </button>
          {/* チャート画像ボタン: matplotlib 生成の PNG を別タブで表示 */}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleOpenChart}
            disabled={openingChart}
          >
            {openingChart ? "取得中..." : "チャート画像"}
          </button>
        </div>
      </div>

      {/* データソースバッジ: どのデータソースから取得しているか表示 */}
      {data?.source && (
        <div className="source-badge">
          データソース: {SOURCE_LABELS[data.source] ?? data.source}
        </div>
      )}

      {/* エラーバナー: API 取得失敗時のエラーメッセージ */}
      {error && <div className="error-banner">{error}</div>}

      {/* メインコンテンツ: データ取得成功時のみ表示 */}
      {data && (
        <>
          {/* 上部サマリーグリッド: 価格・RSI・MACD・ML予測 */}
          <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
            <div className="stat-item">
              <div className="label">
                {/*
                 * リアルタイム価格受信中は "リアルタイム" + LIVE バッジ表示。
                 * WebSocket 未接続または価格未受信時は "終値" ラベルで最終終値を表示。
                 */}
                {liveQuote?.price ? "リアルタイム" : "終値"}
                {connected && liveQuote?.price ? (
                  <span className="badge badge-buy" style={{ marginLeft: "0.35rem", fontSize: "0.65rem" }}>
                    LIVE
                  </span>
                ) : null}
              </div>
              {/* リアルタイム価格を優先、なければテクニカルデータの終値を使用 */}
              <div className="value">{liveQuote?.price ?? data.latest.close}</div>
            </div>
            <div className="stat-item">
              <div className="label">RSI (14)</div>
              {/* RSI は小数点 1 桁で表示（例: "52.3"）*/}
              <div className="value">{data.latest.rsi?.toFixed(1) ?? "-"}</div>
            </div>
            <div className="stat-item">
              <div className="label">MACD</div>
              {/* MACD は小数点 4 桁で表示（FX の価格精度に合わせた桁数）*/}
              <div className="value">{data.latest.macd?.toFixed(4) ?? "-"}</div>
            </div>
            {/* ML 予測結果: モデルの予測が成功した場合のみ表示 */}
            {prediction?.status === "success" && (
              <>
                <div className="stat-item">
                  <div className="label">ML予測価格</div>
                  <div className="value">{prediction.prediction}</div>
                </div>
                <div className="stat-item">
                  <div className="label">モデル精度 (R²)</div>
                  {/* R² スコア: 1.0 に近いほど予測精度が高い */}
                  <div className="value">{prediction.test_r2}</div>
                </div>
              </>
            )}
          </div>

          {/* マルチタイムフレームパネル: 日足・4時間足の整合性表示 */}
          <MultiTimeframePanel symbol={symbol} />

          {/* メインコンテンツグリッド: チャート・シグナル・ツールパネル */}
          <div className="grid-2 mobile-dashboard">
            {/* チャートカード: 全幅表示（gridColumn: 1 / -1 で 2 カラムを跨ぐ）*/}
            <div className="card mobile-chart-block" style={{ gridColumn: "1 / -1" }}>
              {/* タブナビゲーション: 表示するチャートの種類を切り替える */}
              <div className="tabs">
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

              {/* タブ選択に応じたチャートコンポーネントを条件付きレンダリング */}
              {activeTab === "price" && <PriceChart data={data} showMA />}
              {activeTab === "bb" && <PriceChart data={data} showBB />}
              {activeTab === "ichimoku" && <PriceChart data={data} showIchimoku />}
              {activeTab === "rsi" && <OscillatorChart data={data} type="rsi" />}
              {activeTab === "macd" && <OscillatorChart data={data} type="macd" />}
              {activeTab === "stochastic" && <OscillatorChart data={data} type="stochastic" />}
            </div>

            {/*
             * モバイル向けレイアウト制御クラス。
             * mobile-signals-first: モバイルではシグナルパネルを先に表示
             */}
            <div className="mobile-signals-first">
              <SignalPanel signals={signals} price={price} symbol={symbol} />
            </div>
            {/* ポジションサイズ計算パネル */}
            <div className="mobile-extra-panel">
              <PositionSizePanel symbol={symbol} price={price} days={days} />
            </div>
            {/* バックテストパネル */}
            <div className="mobile-extra-panel">
              <BacktestPanel symbol={symbol} days={days} />
            </div>
          </div>
        </>
      )}
    </>
  );
}
