/**
 * @file useLivePrices.ts
 * @description リアルタイム為替価格を取得するカスタムフック。
 *
 * WebSocket 接続を第一選択とし、接続できない場合はポーリング（3 秒間隔）に
 * 自動フォールバックする二重フェイルセーフ設計になっている。
 *
 * 動作フロー:
 * 1. WebSocket 接続を試みる（JWT トークンをクエリパラメータで渡す）
 * 2. 4 秒以内に OPEN 状態にならなければ接続を閉じてポーリングへ切り替える
 * 3. WebSocket が切断された場合もポーリングへ移行する
 * 4. コンポーネントのアンマウント時に WebSocket とポーリングの両方をクリーンアップする
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "@/lib/auth";

/**
 * リアルタイム為替レートの単一クォートを表す型。
 *
 * bid/ask が取得できる場合はそれぞれ設定され、
 * スプレッドのないデータソースでは `price` のみ設定される。
 */
export type LiveQuote = {
  /** 通貨ペアシンボル（例: `"USDJPY"`） */
  symbol: string;
  /** 買値（Bid） */
  bid?: number;
  /** 売値（Ask） */
  ask?: number;
  /** 中間価格（bid/ask が不明な場合） */
  price?: number;
  /** データソース識別子（例: `"oanda"` / `"yahoo_finance"`） */
  source?: string;
  /** 価格の更新日時（ISO 8601 形式） */
  time?: string;
};

/**
 * WebSocket 接続先の基底 URL を解決する。
 *
 * 優先順位:
 * 1. `NEXT_PUBLIC_API_URL` が設定されている場合 → `http(s)://` を `ws(s)://` に変換
 * 2. ブラウザ環境の場合 → 現在のホストの `ws://` または `wss://` を使用
 * 3. それ以外（SSR など）→ `ws://localhost:3000` にフォールバック
 *
 * @returns WebSocket 基底 URL 文字列（末尾スラッシュなし）
 */
function wsBaseUrl(): string {
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) {
    // https:// → wss:// / http:// → ws:// に変換
    return api.replace(/^http/, "ws");
  }
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}`;
  }
  return "ws://localhost:3000";
}

/**
 * Next.js BFF 経由でライブ価格を HTTP ポーリング取得する（WebSocket フォールバック用）。
 *
 * エンドポイント: GET /api/prices/live?symbols={symbols}
 * ※このエンドポイントは Next.js の API ルートであり、バックエンドへプロキシされる。
 *
 * @param symbols - 取得するシンボルの配列
 * @returns シンボルをキーとした {@link LiveQuote} のマップ（取得失敗時は空オブジェクト）
 */
async function fetchLivePrices(symbols: string[]): Promise<Record<string, LiveQuote>> {
  const res = await fetch(`/api/prices/live?symbols=${symbols.join(",")}`, { cache: "no-store" });
  if (!res.ok) return {};
  const body = (await res.json()) as { prices: Record<string, LiveQuote> };
  return body.prices ?? {};
}

/**
 * 複数通貨ペアのリアルタイム価格を購読するカスタムフック。
 *
 * WebSocket を優先的に使用し、接続失敗時はポーリングに自動フォールバックする。
 * `enabled` が `false` の場合はすべての接続処理をスキップする（タブ非表示時の最適化用）。
 *
 * @param symbols - 購読する通貨ペアシンボルの配列（例: `["USDJPY", "EURUSD"]`）
 * @param enabled - `true` の場合のみ接続を開始する（デフォルト `true`）
 * @returns `quotes` — シンボルをキーとした最新クォートのマップ,
 *          `connected` — データソース（WebSocket またはポーリング）に接続中かどうか
 */
export function useLivePrices(symbols: string[], enabled = true) {
  /** シンボルごとの最新クォートを保持するステート */
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});

  /** WebSocket またはポーリングが接続中かどうかを示すステート */
  const [connected, setConnected] = useState(false);

  /** WebSocket インスタンスへの参照（クリーンアップ用） */
  const wsRef = useRef<WebSocket | null>(null);

  /** ポーリングのインターバル ID への参照（クリーンアップ用） */
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // 無効化・シンボルなし・SSR の場合は何もしない
    if (!enabled || symbols.length === 0 || typeof window === "undefined") return;

    /** ポーリングモードに切り替え済みかどうかのフラグ（クロージャで WebSocket の onclose と共有） */
    let usePolling = false;

    /**
     * HTTP ポーリングを開始する内部関数。
     * すでにポーリング中の場合は何もしない（二重起動防止）。
     * 3 秒ごとに `fetchLivePrices` を呼び出して quotes を更新する。
     */
    const startPolling = () => {
      if (pollRef.current) return;
      usePolling = true;
      setConnected(true);
      const poll = async () => {
        const data = await fetchLivePrices(symbols);
        // データが取得できた場合のみ更新（空レスポンスで上書きしない）
        if (Object.keys(data).length) setQuotes(data);
      };
      // 初回即時実行
      poll();
      // 3 秒ごとに定期実行
      pollRef.current = setInterval(poll, 3000);
    };

    // JWT トークンが存在する場合は WebSocket 認証クエリパラメータに付与する
    const token = getAccessToken();
    const qs = token ? `?token=${encodeURIComponent(token)}` : "";

    // WebSocket 接続を開始する
    const ws = new WebSocket(`${wsBaseUrl()}/api/ws/prices${qs}`);
    wsRef.current = ws;

    /** WebSocket 接続確立時: 接続済み状態にして購読シンボルと更新間隔を送信する */
    ws.onopen = () => {
      setConnected(true);
      // サーバーに購読シンボルと更新間隔（秒）を通知する
      ws.send(JSON.stringify({ symbols, interval: 3 }));
    };

    /** WebSocket メッセージ受信時: `type === "prices"` のメッセージのみ処理する */
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as { type: string; data: Record<string, LiveQuote> };
        if (msg.type === "prices" && msg.data) {
          setQuotes(msg.data);
        }
      } catch {
        // JSON パースエラーは無視（不正なメッセージを受け取った場合）
        // ignore
      }
    };

    /** WebSocket 切断時: ポーリングモードへフォールバックする（すでにポーリング中なら何もしない） */
    ws.onclose = () => {
      if (!usePolling) startPolling();
    };

    /** WebSocket エラー時: 接続を閉じてポーリングへ切り替える */
    ws.onerror = () => {
      ws.close();
      startPolling();
    };

    // WebSocket が 4 秒以内に OPEN にならない場合はポーリングへフォールバックする
    const fallbackTimer = setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        ws.close();
        startPolling();
      }
    }, 4000);

    // エフェクトのクリーンアップ: コンポーネントアンマウント時またはシンボル変化時に実行
    return () => {
      clearTimeout(fallbackTimer);
      // WebSocket を閉じる
      ws.close();
      wsRef.current = null;
      // ポーリングを停止する
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  // symbols を join した文字列で依存配列を構成（配列参照の変化を無視するため）
  }, [enabled, symbols.join(",")]);

  return { quotes, connected };
}
