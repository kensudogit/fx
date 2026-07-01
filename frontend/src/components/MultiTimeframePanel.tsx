/**
 * @file MultiTimeframePanel.tsx
 * @description マルチタイムフレーム分析パネル
 *
 * 日足（1d）と 4 時間足（4h）のトレンド・RSI・シグナルバイアスを
 * 並べて表示し、複数時間軸の整合性（アライメント）を一目で確認できる。
 * テクニカルダッシュボードの補助パネルとして組み込まれる。
 */

"use client";

import { useEffect, useState } from "react";
import { getMultiTimeframe } from "@/lib/api";
import type { MultiTimeframeAnalysis } from "@/types";

/**
 * トレンド種別 → CSS バッジクラス名のマッピング。
 * - bullish（上昇トレンド）: 青系「買い」バッジ
 * - bearish（下降トレンド）: 赤系「売り」バッジ
 * - neutral（中立）        : グレー系「中立」バッジ
 */
const TREND_CLASS: Record<string, string> = {
  bullish: "badge-buy",
  bearish: "badge-sell",
  neutral: "badge-neutral",
};

/**
 * MultiTimeframePanel のプロパティ型定義。
 * @property symbol - 分析対象の通貨ペアシンボル（例: "USDJPY"）
 */
type Props = { symbol: string };

/**
 * MultiTimeframePanel
 *
 * 指定シンボルの複数時間軸（日足・4時間足）テクニカル分析を表示する。
 * マウント時・シンボル変更時に API からデータを取得し、
 * 各時間軸のトレンド方向・RSI 値・シグナルバイアスをカード形式で並べる。
 *
 * データが未取得または取得失敗の場合はコンポーネント全体を非表示にする。
 *
 * @param props - {@link Props}
 */
export default function MultiTimeframePanel({ symbol }: Props) {
  /**
   * マルチタイムフレーム分析データ。
   * 初期値 null: データ未取得またはエラー時は何も表示しない
   */
  const [data, setData] = useState<MultiTimeframeAnalysis | null>(null);

  /**
   * symbol が変わるたびに API を再取得する。
   * - 取得成功: data を更新して再レンダリング
   * - 取得失敗: null をセットしてパネルを非表示にする（エラー表示は行わない）
   *
   * 依存配列: [symbol] — シンボルが変更された時だけ再フェッチ
   */
  useEffect(() => {
    getMultiTimeframe(symbol).then(setData).catch(() => setData(null));
  }, [symbol]);

  // データが存在しない場合はパネル全体を非表示にする（ローディング中も同様）
  if (!data) return null;

  // 表示する時間軸の定数配列（日足と4時間足の2種類）
  const frames = ["1d", "4h"] as const;

  return (
    <div className="card trader-tool-card">
      <h2>マルチタイムフレーム</h2>
      {/* 複数時間軸のトレンド整合性ラベル（例: "全時間軸で買い優勢" など） */}
      <p className="alignment-banner">{data.alignment_label}</p>
      <div className="mtf-grid">
        {frames.map((tf) => {
          // 該当する時間軸データが存在しない場合はスキップ
          const t = data.timeframes[tf];
          if (!t) return null;
          return (
            <div key={tf} className="mtf-item">
              <div className="mtf-head">
                {/* 日足 / 4時間足 の日本語ラベルを表示 */}
                <strong>{tf === "1d" ? "日足" : "4時間足"}</strong>
                {/*
                 * トレンドに対応するバッジを表示。
                 * TREND_CLASS マッピングで bullish/bearish/neutral を色分け。
                 * 未知のトレンド値の場合は空文字クラスにフォールバック。
                 */}
                <span className={`badge ${TREND_CLASS[t.trend] ?? ""}`}>{t.label}</span>
              </div>
              <div className="mtf-meta">
                {/* RSI 値（取得できない場合はダッシュ表示） */}
                <span>RSI {t.rsi ?? "—"}</span>
                {/* シグナルバイアス: buy / sell / それ以外（中立） を日本語で表示 */}
                <span>シグナル: {t.signal_bias === "buy" ? "買い" : t.signal_bias === "sell" ? "売り" : "中立"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
