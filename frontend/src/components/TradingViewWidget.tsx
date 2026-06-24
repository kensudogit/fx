"use client";

import { useEffect, useRef } from "react";

const TV_SYMBOL: Record<string, string> = {
  USDJPY: "OANDA:USDJPY",
  EURUSD: "OANDA:EURUSD",
  GBPUSD: "OANDA:GBPUSD",
  AUDUSD: "OANDA:AUDUSD",
};

interface TradingViewWidgetProps {
  symbol: string;
}

export default function TradingViewWidget({ symbol }: TradingViewWidgetProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.innerHTML = "";
    const widgetId = `tv_${symbol}`;
    el.id = widgetId;

    const mount = () => {
      const tv = (window as unknown as { TradingView?: { widget: (o: object) => void } })
        .TradingView;
      if (!tv) return;
      tv.widget({
        autosize: true,
        symbol: TV_SYMBOL[symbol] ?? `OANDA:${symbol}`,
        interval: "240",
        timezone: "Asia/Tokyo",
        theme: "dark",
        style: "1",
        locale: "ja",
        toolbar_bg: "#1a2332",
        enable_publishing: false,
        container_id: widgetId,
      });
    };

    if ((window as unknown as { TradingView?: unknown }).TradingView) {
      mount();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/tv.js";
    script.async = true;
    script.onload = mount;
    document.body.appendChild(script);
  }, [symbol]);

  return (
    <div className="card tv-widget-card">
      <h2>TradingView チャート</h2>
      <p className="hint">
        Pine Script アラートを Webhook に送信するとシグナルが記録されます（
        <code>backend/pine/fx_webhook_strategy.pine</code>）
      </p>
      <div ref={containerRef} className="tv-widget" />
    </div>
  );
}
