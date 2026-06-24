"use client";

import type { TradingSignal } from "@/types";

interface SignalPanelProps {
  signals: TradingSignal[];
  price: number;
  symbol: string;
}

export default function SignalPanel({ signals, price, symbol }: SignalPanelProps) {
  const buyCount = signals.filter((s) => s.signal === "buy").length;
  const sellCount = signals.filter((s) => s.signal === "sell").length;

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
      <h2>トレードシグナル - {symbol}</h2>
      <div className="stat-grid" style={{ marginBottom: "1rem" }}>
        <div className="stat-item">
          <div className="label">現在価格</div>
          <div className="value">{price}</div>
        </div>
        <div className="stat-item">
          <div className="label">総合判断</div>
          <div className="value">
            <span className={`badge ${overallClass}`}>{overall}</span>
          </div>
        </div>
        <div className="stat-item">
          <div className="label">買いシグナル</div>
          <div className="value" style={{ color: "var(--buy)" }}>
            {buyCount}
          </div>
        </div>
        <div className="stat-item">
          <div className="label">売りシグナル</div>
          <div className="value" style={{ color: "var(--sell)" }}>
            {sellCount}
          </div>
        </div>
      </div>
      {signals.length === 0 ? (
        <p style={{ color: "var(--text-secondary)" }}>現在シグナルはありません</p>
      ) : (
        signals.map((s, i) => (
          <div key={i} className={s.signal === "buy" ? "signal-buy" : "signal-sell"}>
            <strong>{s.indicator}</strong>
            {" - "}
            <span className={`badge badge-${s.signal}`}>
              {s.signal === "buy" ? "買い" : "売り"}
            </span>
            {s.value !== undefined && ` (${s.value})`}
            <div style={{ fontSize: "0.85rem", marginTop: "0.25rem" }}>{s.reason}</div>
          </div>
        ))
      )}
    </div>
  );
}
