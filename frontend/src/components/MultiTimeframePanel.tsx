"use client";

import { useEffect, useState } from "react";
import { getMultiTimeframe } from "@/lib/api";
import type { MultiTimeframeAnalysis } from "@/types";

const TREND_CLASS: Record<string, string> = {
  bullish: "badge-buy",
  bearish: "badge-sell",
  neutral: "badge-neutral",
};

type Props = { symbol: string };

export default function MultiTimeframePanel({ symbol }: Props) {
  const [data, setData] = useState<MultiTimeframeAnalysis | null>(null);

  useEffect(() => {
    getMultiTimeframe(symbol).then(setData).catch(() => setData(null));
  }, [symbol]);

  if (!data) return null;

  const frames = ["1d", "4h"] as const;

  return (
    <div className="card trader-tool-card">
      <h2>マルチタイムフレーム</h2>
      <p className="alignment-banner">{data.alignment_label}</p>
      <div className="mtf-grid">
        {frames.map((tf) => {
          const t = data.timeframes[tf];
          if (!t) return null;
          return (
            <div key={tf} className="mtf-item">
              <div className="mtf-head">
                <strong>{tf === "1d" ? "日足" : "4時間足"}</strong>
                <span className={`badge ${TREND_CLASS[t.trend] ?? ""}`}>{t.label}</span>
              </div>
              <div className="mtf-meta">
                <span>RSI {t.rsi ?? "—"}</span>
                <span>シグナル: {t.signal_bias === "buy" ? "買い" : t.signal_bias === "sell" ? "売り" : "中立"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
