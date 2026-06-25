"use client";

import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "@/lib/auth";

export type LiveQuote = {
  symbol: string;
  bid?: number;
  ask?: number;
  price?: number;
  source?: string;
  time?: string;
};

function wsBaseUrl(): string {
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) {
    return api.replace(/^http/, "ws");
  }
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}`;
  }
  return "ws://localhost:3000";
}

async function fetchLivePrices(symbols: string[]): Promise<Record<string, LiveQuote>> {
  const res = await fetch(`/api/prices/live?symbols=${symbols.join(",")}`, { cache: "no-store" });
  if (!res.ok) return {};
  const body = (await res.json()) as { prices: Record<string, LiveQuote> };
  return body.prices ?? {};
}

export function useLivePrices(symbols: string[], enabled = true) {
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled || symbols.length === 0 || typeof window === "undefined") return;

    let usePolling = false;

    const startPolling = () => {
      if (pollRef.current) return;
      usePolling = true;
      setConnected(true);
      const poll = async () => {
        const data = await fetchLivePrices(symbols);
        if (Object.keys(data).length) setQuotes(data);
      };
      poll();
      pollRef.current = setInterval(poll, 3000);
    };

    const token = getAccessToken();
    const qs = token ? `?token=${encodeURIComponent(token)}` : "";
    const ws = new WebSocket(`${wsBaseUrl()}/api/ws/prices${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ symbols, interval: 3 }));
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as { type: string; data: Record<string, LiveQuote> };
        if (msg.type === "prices" && msg.data) {
          setQuotes(msg.data);
        }
      } catch {
        // ignore
      }
    };

    ws.onclose = () => {
      if (!usePolling) startPolling();
    };
    ws.onerror = () => {
      ws.close();
      startPolling();
    };

    const fallbackTimer = setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        ws.close();
        startPolling();
      }
    }, 4000);

    return () => {
      clearTimeout(fallbackTimer);
      ws.close();
      wsRef.current = null;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [enabled, symbols.join(",")]);

  return { quotes, connected };
}
