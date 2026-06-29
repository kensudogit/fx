/**
 * React コンポーネント — PositionSizePanel
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useState } from "react";
import { getPositionSize } from "@/lib/api";
import type { PositionSizeResult } from "@/types";

type Props = {
  symbol: string;
  price: number;
  days: number;
};

export default function PositionSizePanel({ symbol, price, days }: Props) {
  const [balance, setBalance] = useState(10000);
  const [risk, setRisk] = useState(1);
  const [stopPips, setStopPips] = useState("");
  const [result, setResult] = useState<PositionSizeResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    const opts: { accountBalance: number; riskPercent: number; stopPips?: number; days: number } = {
      accountBalance: balance,
      riskPercent: risk,
      days,
    };
    if (stopPips) opts.stopPips = Number(stopPips);
    getPositionSize(symbol, opts)
      .then(setResult)
      .catch(() => setResult(null))
      .finally(() => setLoading(false));
  }, [symbol, balance, risk, stopPips, days]);

  return (
    <div className="card trader-tool-card">
      <h2>ポジションサイズ計算</h2>
      <p className="tool-hint">ATR ベースのストップ幅から推奨ロットを算出（口座リスク%管理）</p>
      <div className="tool-form grid-2">
        <div className="form-group">
          <label>口座残高 (USD)</label>
          <input type="number" value={balance} onChange={(e) => setBalance(Number(e.target.value))} min={100} />
        </div>
        <div className="form-group">
          <label>リスク (%)</label>
          <input type="number" value={risk} onChange={(e) => setRisk(Number(e.target.value))} min={0.1} max={10} step={0.1} />
        </div>
        <div className="form-group">
          <label>ストップ (pips) — 空欄でATR</label>
          <input type="number" value={stopPips} onChange={(e) => setStopPips(e.target.value)} placeholder="自動" />
        </div>
        <div className="form-group">
          <label>現在価格</label>
          <input type="text" value={price} readOnly />
        </div>
      </div>
      {loading && <p className="tool-hint">計算中...</p>}
      {result && !loading && (
        <div className="stat-grid" style={{ marginTop: "0.75rem" }}>
          <div className="stat-item">
            <div className="label">推奨ロット</div>
            <div className="value highlight">{result.recommended_lots}</div>
          </div>
          <div className="stat-item">
            <div className="label">ストップ</div>
            <div className="value">{result.stop_pips} pips{result.atr_based_stop ? " (ATR)" : ""}</div>
          </div>
          <div className="stat-item">
            <div className="label">最大損失</div>
            <div className="value" style={{ color: "var(--sell)" }}>${result.max_loss_usd}</div>
          </div>
          <div className="stat-item">
            <div className="label">利確目安</div>
            <div className="value" style={{ color: "var(--buy)" }}>{result.suggested_take_profit_pips} pips</div>
          </div>
        </div>
      )}
    </div>
  );
}
