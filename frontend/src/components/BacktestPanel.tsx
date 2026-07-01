/**
 * @file BacktestPanel.tsx
 * @description シグナルバックテストパネル — ルールベースシグナルの過去検証結果表示
 *
 * 指定された通貨ペアと検証日数で getSignalBacktest() を呼び出し、
 * 翌日方向ヒット率（勝率）・平均リターン・取引内訳を小型カードで表示する。
 * データ取得失敗またはトレード数が 0 件の場合は何も描画しない（null を返す）。
 *
 * 親コンポーネント（IntegrationDashboard など）からプロップスで
 * symbol と days を受け取り、変化するたびに自動で再取得する。
 */

"use client";

import { useEffect, useState } from "react";
import { getSignalBacktest } from "@/lib/api";
import type { SignalBacktest } from "@/types";

/**
 * Props — BacktestPanel のプロップス型
 */
type Props = {
  /** バックテスト対象の通貨ペア（例: "USDJPY"） */
  symbol: string;
  /** バックテストの検証期間（日数）— 例: 30, 90, 365 */
  days: number;
};

/**
 * BacktestPanel
 *
 * ルールベースシグナルの翌日方向ヒット率を表示する軽量カードコンポーネント。
 * symbol / days が変化するたびに API を呼び直し、結果をカードに反映する。
 * データがない場合は非表示（null 返却）のため、親レイアウトを崩さない。
 *
 * @param symbol - 分析対象の通貨ペア
 * @param days   - 検証対象期間（日数）
 */
export default function BacktestPanel({ symbol, days }: Props) {
  /** バックテスト結果データ — 取得中または取得失敗時は null */
  const [data, setData] = useState<SignalBacktest | null>(null);

  /**
   * symbol または days が変化するたびにバックテスト結果を取得する副作用
   * エラー発生時は data を null にリセットして非表示にする（エラー表示不要）
   */
  useEffect(() => {
    getSignalBacktest(symbol, days).then(setData).catch(() => setData(null));
  }, [symbol, days]);

  /** データなし or トレード数 0 件の場合はレンダリングをスキップ */
  if (!data || data.total_trades === 0) return null;

  return (
    <div className="card trader-tool-card">
      <h2>シグナルバックテスト</h2>
      <p className="tool-hint">過去データでルールベースシグナルの翌日方向ヒット率（参考値）</p>
      <div className="stat-grid">
        {/* 勝率 — highlight クラスで強調表示 */}
        <div className="stat-item">
          <div className="label">勝率</div>
          <div className="value highlight">{data.win_rate}%</div>
        </div>
        {/* 総トレード数 */}
        <div className="stat-item">
          <div className="label">トレード数</div>
          <div className="value">{data.total_trades}</div>
        </div>
        {/* 翌日の平均リターン（%) */}
        <div className="stat-item">
          <div className="label">平均リターン</div>
          <div className="value">{data.avg_return_pct}%</div>
        </div>
        {/* 買いシグナル数 / 売りシグナル数 */}
        <div className="stat-item">
          <div className="label">買い / 売り</div>
          <div className="value">{data.buy_trades} / {data.sell_trades}</div>
        </div>
      </div>
    </div>
  );
}
