/**
 * @file useLivePrices.test.ts
 * @description `src/lib/useLivePrices.ts`（リアルタイム価格購読フック）のユニットテスト。
 *
 * 検証範囲:
 * - WebSocket 接続 URL の組み立て（NEXT_PUBLIC_API_URL / ブラウザホスト / トークン付与）
 * - onopen での購読メッセージ送信と connected フラグ
 * - onmessage での quotes 更新（type が prices 以外・不正 JSON は無視）
 * - WebSocket 失敗時（onerror / onclose / 4 秒タイムアウト）のポーリングフォールバック
 * - enabled=false / symbols 空のときに何も接続しないこと
 * - アンマウント時のクリーンアップ
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useLivePrices } from "./useLivePrices";
import { setAccessToken } from "./auth";
import { jsonResponse, mockFetch } from "@/test/utils";

/**
 * jsdom には WebSocket が無いため、テストから状態遷移を制御できるフェイクを用意する。
 * 生成されたインスタンスは `FakeWebSocket.instances` から参照できる。
 */
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  /** テスト中に生成された全インスタンス */
  static instances: FakeWebSocket[] = [];

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  closed = false;

  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
  }

  /** サーバーが接続を受理した状態をシミュレートする */
  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  /** サーバーからのメッセージ受信をシミュレートする */
  simulateMessage(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }
}

/** 直近に生成された FakeWebSocket を返す */
function latestSocket(): FakeWebSocket {
  const ws = FakeWebSocket.instances.at(-1);
  if (!ws) throw new Error("WebSocket が生成されていません");
  return ws;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useLivePrices — 接続の初期化", () => {
  it("ブラウザのホストから ws:// の URL を組み立てる", () => {
    mockFetch();
    renderHook(() => useLivePrices(["USDJPY"]));
    expect(latestSocket().url).toBe(`ws://${window.location.host}/api/ws/prices`);
  });

  it("JWT がある場合は token クエリパラメータを付与する", () => {
    mockFetch();
    setAccessToken("jwt a/b");
    renderHook(() => useLivePrices(["USDJPY"]));
    expect(latestSocket().url).toContain(`?token=${encodeURIComponent("jwt a/b")}`);
  });

  it("NEXT_PUBLIC_API_URL が設定されていれば http→ws に変換して使う", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");
    vi.resetModules();
    const { useLivePrices: hook } = await import("./useLivePrices");

    mockFetch();
    renderHook(() => hook(["USDJPY"]));
    expect(latestSocket().url).toBe("wss://api.example.com/api/ws/prices");
  });

  it("enabled=false のときは接続しない", () => {
    mockFetch();
    const { result } = renderHook(() => useLivePrices(["USDJPY"], false));
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(result.current.connected).toBe(false);
  });

  it("symbols が空配列のときは接続しない", () => {
    mockFetch();
    renderHook(() => useLivePrices([]));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});

describe("useLivePrices — WebSocket 経由の更新", () => {
  it("接続確立時に購読シンボルと更新間隔を送信し connected になる", async () => {
    mockFetch();
    const { result } = renderHook(() => useLivePrices(["USDJPY", "EURUSD"]));

    act(() => latestSocket().simulateOpen());

    expect(JSON.parse(latestSocket().sent[0])).toEqual({
      symbols: ["USDJPY", "EURUSD"],
      interval: 3,
    });
    await waitFor(() => expect(result.current.connected).toBe(true));
  });

  it("type=prices のメッセージで quotes を更新する", async () => {
    mockFetch();
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));
    act(() => latestSocket().simulateOpen());

    const payload = { USDJPY: { symbol: "USDJPY", bid: 151.4, ask: 151.42, price: 151.41 } };
    act(() => latestSocket().simulateMessage({ type: "prices", data: payload }));

    await waitFor(() => expect(result.current.quotes).toEqual(payload));
  });

  it("type が prices 以外のメッセージは無視する", async () => {
    mockFetch();
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));
    act(() => latestSocket().simulateOpen());

    act(() => latestSocket().simulateMessage({ type: "pong", data: { USDJPY: { price: 1 } } }));

    expect(result.current.quotes).toEqual({});
  });

  it("不正な JSON を受信しても例外を投げない", async () => {
    mockFetch();
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));
    act(() => latestSocket().simulateOpen());

    expect(() => act(() => latestSocket().simulateMessage("not json"))).not.toThrow();
    expect(result.current.quotes).toEqual({});
  });
});

describe("useLivePrices — ポーリングへのフォールバック", () => {
  it("onerror で接続を閉じてポーリングへ切り替える", async () => {
    const f = mockFetch(() =>
      jsonResponse({ prices: { USDJPY: { symbol: "USDJPY", price: 151.5 } } }),
    );
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));

    await act(async () => {
      latestSocket().onerror?.();
      await Promise.resolve();
    });

    expect(latestSocket().closed).toBe(true);
    await waitFor(() => expect(result.current.connected).toBe(true));
    await waitFor(() => expect(result.current.quotes.USDJPY?.price).toBe(151.5));
    expect(String(f.mock.calls[0][0])).toBe("/api/prices/live?symbols=USDJPY");
  });

  it("WebSocket が閉じられたらポーリングへ移行する", async () => {
    const f = mockFetch(() => jsonResponse({ prices: {} }));
    renderHook(() => useLivePrices(["USDJPY"]));

    await act(async () => {
      latestSocket().onclose?.();
      await Promise.resolve();
    });

    expect(f).toHaveBeenCalled();
  });

  it("4 秒以内に OPEN にならなければポーリングへ切り替える", async () => {
    vi.useFakeTimers();
    const f = mockFetch(() => jsonResponse({ prices: {} }));
    renderHook(() => useLivePrices(["USDJPY"]));

    expect(f).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(4000);
    });

    expect(latestSocket().closed).toBe(true);
    expect(f).toHaveBeenCalled();
  });

  it("OPEN 済みなら 4 秒後もポーリングへ切り替えない", async () => {
    vi.useFakeTimers();
    const f = mockFetch(() => jsonResponse({ prices: {} }));
    renderHook(() => useLivePrices(["USDJPY"]));

    act(() => latestSocket().simulateOpen());
    await act(async () => {
      vi.advanceTimersByTime(4000);
    });

    expect(f).not.toHaveBeenCalled();
  });

  it("ポーリングは 3 秒ごとに実行される", async () => {
    vi.useFakeTimers();
    const f = mockFetch(() => jsonResponse({ prices: {} }));
    renderHook(() => useLivePrices(["USDJPY"]));

    await act(async () => {
      latestSocket().onerror?.();
    });
    const initialCalls = f.mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });

    expect(f.mock.calls.length).toBe(initialCalls + 2);
  });

  it("ポーリングが空レスポンスを返しても既存の quotes を上書きしない", async () => {
    let body: unknown = { prices: { USDJPY: { symbol: "USDJPY", price: 151.5 } } };
    mockFetch(() => jsonResponse(body));
    vi.useFakeTimers();
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));

    // フェイクタイマー下では waitFor が進まないため、マイクロタスクを直接消化する
    await act(async () => {
      latestSocket().onerror?.();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.quotes.USDJPY?.price).toBe(151.5);

    body = { prices: {} };
    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.quotes.USDJPY?.price).toBe(151.5);
  });

  it("ポーリングの HTTP エラーは空マップとして扱う", async () => {
    mockFetch(() => jsonResponse({ detail: "error" }, { status: 500 }));
    const { result } = renderHook(() => useLivePrices(["USDJPY"]));

    await act(async () => {
      latestSocket().onerror?.();
      await Promise.resolve();
    });

    expect(result.current.quotes).toEqual({});
  });
});

describe("useLivePrices — クリーンアップ", () => {
  it("アンマウント時に WebSocket を閉じる", () => {
    mockFetch();
    const { unmount } = renderHook(() => useLivePrices(["USDJPY"]));
    const ws = latestSocket();

    unmount();

    expect(ws.closed).toBe(true);
  });

  it("アンマウント後はポーリングが実行されない", async () => {
    vi.useFakeTimers();
    const f = mockFetch(() => jsonResponse({ prices: {} }));
    const { unmount } = renderHook(() => useLivePrices(["USDJPY"]));

    await act(async () => {
      latestSocket().onerror?.();
    });
    const callsBeforeUnmount = f.mock.calls.length;

    unmount();
    await act(async () => {
      vi.advanceTimersByTime(9000);
    });

    expect(f.mock.calls.length).toBe(callsBeforeUnmount);
  });

  it("symbols が変わると WebSocket を張り直す", () => {
    mockFetch();
    const { rerender } = renderHook(({ s }: { s: string[] }) => useLivePrices(s), {
      initialProps: { s: ["USDJPY"] },
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ s: ["EURUSD"] });

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[0].closed).toBe(true);
  });

  it("symbols の中身が同じなら再接続しない（join 文字列で依存を判定）", () => {
    mockFetch();
    const { rerender } = renderHook(({ s }: { s: string[] }) => useLivePrices(s), {
      initialProps: { s: ["USDJPY"] },
    });

    // 参照は異なるが内容が同じ配列を渡す
    rerender({ s: ["USDJPY"] });

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
