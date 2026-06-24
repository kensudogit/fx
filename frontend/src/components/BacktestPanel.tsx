"use client";

import { useEffect, useState } from "react";
import { getSignalBacktest } from "@/lib/api";
import type { SignalBacktest } from "@/types";

type Props = { symbol: string; days: number };

export default function BacktestPanel({ symbol, days }: Props) {
  const [data, setData] = useState<SignalBacktest | null>(null);

  useEffect(() => {
    getSignalBacktest(symbol, days).then(setData).catch(() => setData(null));
  }, [symbol, days]);

  if (!data || data.total_trades === 0) return null;

  return (
    <div className="card trader-tool-card">
      <h2>シグナルバックテスト</h2>
      <p className="tool-hint">過去データでルールベースシグナルの翌日方向ヒット率（参考値）</p>
      <div className="stat-grid">
        <div className="stat-item">
          <div className="label">勝率</div>
          <div className="value highlight">{data.win_rate}%</div>
        </div>
        <div className="stat-item">
          <div className="label">トレード数</div>
          <div className="value">{data.total_trades}</div>
        </div>
        <div className="stat-item">
          <div className="label">平均リターン</div>
          <div className="value">{data.avg_return_pct}%</div>
        </div>
        <div className="stat-item">
          <div className="label">買い / 売り</div>
          <div className="value">{data.buy_trades} / {data.sell_trades}</div>
        </div>
      </div>
    </div>
  );
}
