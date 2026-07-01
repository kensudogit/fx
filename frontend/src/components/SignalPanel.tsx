/**
 * @file SignalPanel.tsx
 * @description トレードシグナル表示パネル
 *
 * 各種テクニカル指標から生成されたトレードシグナルの一覧と
 * 買い/売りシグナルの集計・総合判断を表示する。
 * テクニカルダッシュボードのメインパネルとして表示される。
 *
 * 表示内容:
 * - 現在価格
 * - 買いシグナル数 / 売りシグナル数の集計
 * - 多数派に基づく総合判断（買い優勢 / 売り優勢 / 中立）
 * - 各シグナルの指標名・方向・値・理由の詳細リスト
 */

"use client";

import type { TradingSignal } from "@/types";

/**
 * SignalPanel のプロパティ型定義。
 * @property signals - テクニカル指標から生成されたシグナルの配列
 * @property price   - 対象通貨ペアの現在価格
 * @property symbol  - 通貨ペアシンボル（例: "USDJPY"）
 */
interface SignalPanelProps {
  /** 各インジケーターから生成されたシグナルの一覧 */
  signals: TradingSignal[];
  /** パネルヘッダーに表示する現在価格 */
  price: number;
  /** 通貨ペアシンボル（パネルタイトルに表示）*/
  symbol: string;
}

/**
 * SignalPanel
 *
 * トレードシグナルの集計と個別シグナル一覧を表示するカードコンポーネント。
 *
 * ### 総合判断ロジック
 * - 買いシグナル数 > 売りシグナル数 → "買い優勢"（badge-buy）
 * - 売りシグナル数 > 買いシグナル数 → "売り優勢"（badge-sell）
 * - 同数または 0 → "中立"（バッジなし）
 *
 * ### シグナルリストの表示
 * - 各シグナルを buy（緑）/ sell（赤）の背景色で色分け
 * - インジケーター名・方向バッジ・値・理由テキストを表示
 * - シグナルがない場合は「現在シグナルはありません」を表示
 *
 * @param props - {@link SignalPanelProps}
 */
export default function SignalPanel({ signals, price, symbol }: SignalPanelProps) {
  // 買いシグナルの件数を集計
  const buyCount = signals.filter((s) => s.signal === "buy").length;
  // 売りシグナルの件数を集計
  const sellCount = signals.filter((s) => s.signal === "sell").length;

  /**
   * 総合判断テキストと対応バッジクラスを決定する。
   * buyCount と sellCount を比較し、多数派を総合判断とする。
   * 同数の場合は「中立」としてバッジクラスは空文字のまま。
   */
  let overall = "中立";
  let overallClass = "";
  if (buyCount > sellCount) {
    overall = "買い優勢";
    overallClass = "badge-buy";
  } else if (sellCount > buyCount) {
    overall = "売り優勢";
    overallClass = "badge-sell";
  }

  return (
    <div className="card">
      {/* パネルタイトル: 対象通貨ペアを併記 */}
      <h2>トレードシグナル - {symbol}</h2>

      {/* 上部サマリーグリッド: 現在価格・総合判断・買い/売りカウント */}
      <div className="stat-grid" style={{ marginBottom: "1rem" }}>
        <div className="stat-item">
          <div className="label">現在価格</div>
          <div className="value">{price}</div>
        </div>
        <div className="stat-item">
          <div className="label">総合判断</div>
          <div className="value">
            {/*
             * overallClass が空の場合（中立）はバッジスタイルなしで表示。
             * 買い優勢/売り優勢はそれぞれ対応するバッジカラーで表示。
             */}
            <span className={`badge ${overallClass}`}>{overall}</span>
          </div>
        </div>
        <div className="stat-item">
          <div className="label">買いシグナル</div>
          {/* 買いシグナル数を緑色（--buy カラー変数）で表示 */}
          <div className="value" style={{ color: "var(--buy)" }}>
            {buyCount}
          </div>
        </div>
        <div className="stat-item">
          <div className="label">売りシグナル</div>
          {/* 売りシグナル数を赤色（--sell カラー変数）で表示 */}
          <div className="value" style={{ color: "var(--sell)" }}>
            {sellCount}
          </div>
        </div>
      </div>

      {/* シグナルリスト */}
      {signals.length === 0 ? (
        // シグナルがない場合のメッセージ
        <p style={{ color: "var(--text-secondary)" }}>現在シグナルはありません</p>
      ) : (
        signals.map((s, i) => (
          /*
           * 各シグナルを buy/sell に応じた CSS クラスで色分け表示。
           * signal-buy: 緑系背景、signal-sell: 赤系背景
           */
          <div key={i} className={s.signal === "buy" ? "signal-buy" : "signal-sell"}>
            {/* インジケーター名（例: "RSI", "MACD", "移動平均"）*/}
            <strong>{s.indicator}</strong>
            {" - "}
            {/* 売買方向バッジ: badge-buy（緑）または badge-sell（赤）*/}
            <span className={`badge badge-${s.signal}`}>
              {s.signal === "buy" ? "買い" : "売り"}
            </span>
            {/* インジケーターの現在値（存在する場合のみ括弧付きで表示）*/}
            {s.value !== undefined && ` (${s.value})`}
            {/* シグナル発生の理由・根拠テキスト（小さいフォントで補足表示）*/}
            <div style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}>{s.reason}</div>
          </div>
        ))
      )}
    </div>
  );
}
