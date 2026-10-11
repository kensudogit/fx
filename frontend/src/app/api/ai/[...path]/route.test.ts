/**
 * @vitest-environment node
 *
 * @file app/api/ai/[...path]/route.test.ts
 * @description AI プロキシ Route Handler のユニットテスト。
 *
 * Route Handler は `NextRequest` / `NextResponse` を使うため Node 環境で実行する。
 *
 * 検証範囲:
 * - 転送先 URL の組み立て（パスセグメントの結合・クエリ文字列の維持）
 * - 認証ヘッダー（authorization / x-api-key / cookie）の選択的転送
 * - 不要なヘッダーを転送しないこと
 * - バックエンドのステータス・Content-Type・ボディをそのまま返すこと
 * - タイムアウト時 504・接続エラー時 502 の日本語メッセージ
 * - GET / POST 双方のハンドラーが同じプロキシ処理を通ること
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./route";

/**
 * テスト用の NextRequest を生成する。
 *
 * @param url - リクエスト URL（クエリを含められる）
 * @param headers - リクエストヘッダー
 * @param method - HTTP メソッド
 */
function request(url: string, headers: Record<string, string> = {}, method = "GET"): NextRequest {
  return new NextRequest(new URL(url, "https://fx.example.com"), { method, headers });
}

/** Next.js 15 のルートコンテキスト（params は Promise で渡される） */
function context(path: string[]) {
  return { params: Promise.resolve({ path }) };
}

/** バックエンドの応答をモックする */
function mockBackend(
  body: string,
  init: { status?: number; contentType?: string } = {},
) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
    status: init.status ?? 200,
    headers: new Headers(
      init.contentType === null ? {} : { "content-type": init.contentType ?? "application/json" },
    ),
    text: async () => body,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** モックされた fetch の n 回目の呼び出し URL を返す */
function calledUrl(fn: ReturnType<typeof mockBackend>, index = 0): string {
  return String(fn.mock.calls[index][0]);
}

/** モックされた fetch の n 回目の呼び出しの RequestInit を返す */
function calledInit(fn: ReturnType<typeof mockBackend>, index = 0): RequestInit {
  return fn.mock.calls[index][1] ?? {};
}

/** モックされた fetch の n 回目の呼び出しで転送されたヘッダーを返す */
function calledHeaders(fn: ReturnType<typeof mockBackend>, index = 0): Headers {
  return calledInit(fn, index).headers as Headers;
}

beforeEach(() => {
  // 502 のパスで console.error が呼ばれるため、テスト出力を汚さないよう抑制する
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("AI プロキシ — 転送先 URL", () => {
  it("パスセグメントを結合してバックエンドの /api/ai/** を呼ぶ", async () => {
    const f = mockBackend("{}");
    await GET(request("/api/ai/news/USDJPY"), context(["news", "USDJPY"]));
    expect(calledUrl(f)).toBe("http://localhost:8000/api/ai/news/USDJPY");
  });

  it("クエリ文字列をそのまま引き継ぐ", async () => {
    const f = mockBackend("{}");
    await GET(
      request("/api/ai/report/USDJPY?account_balance=50000"),
      context(["report", "USDJPY"]),
    );
    expect(calledUrl(f)).toBe("http://localhost:8000/api/ai/report/USDJPY?account_balance=50000");
  });

  it("INTERNAL_API_URL が設定されていればそれを優先する", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.railway.internal:8000");
    vi.resetModules();
    const { GET: handler } = await import("./route");

    const f = mockBackend("{}");
    await handler(request("/api/ai/status"), context(["status"]));

    expect(calledUrl(f)).toBe("http://backend.railway.internal:8000/api/ai/status");
  });
});

describe("AI プロキシ — ヘッダー転送", () => {
  it("authorization / x-api-key / cookie を転送する", async () => {
    const f = mockBackend("{}");
    await GET(
      request("/api/ai/status", {
        authorization: "Bearer jwt-abc",
        "x-api-key": "fx_live_1",
        cookie: "fx_access_token=jwt-abc",
      }),
      context(["status"]),
    );

    const headers = calledHeaders(f);
    expect(headers.get("authorization")).toBe("Bearer jwt-abc");
    expect(headers.get("x-api-key")).toBe("fx_live_1");
    expect(headers.get("cookie")).toBe("fx_access_token=jwt-abc");
  });

  it("accept: application/json を常に設定する", async () => {
    const f = mockBackend("{}");
    await GET(request("/api/ai/status"), context(["status"]));
    expect(calledHeaders(f).get("accept")).toBe("application/json");
  });

  it("認証に不要なヘッダーは転送しない", async () => {
    const f = mockBackend("{}");
    await GET(
      request("/api/ai/status", { "user-agent": "evil", "x-forwarded-for": "10.0.0.1" }),
      context(["status"]),
    );
    const headers = calledHeaders(f);
    expect(headers.get("user-agent")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
  });

  it("存在しない認証ヘッダーは付与しない", async () => {
    const f = mockBackend("{}");
    await GET(request("/api/ai/status"), context(["status"]));
    const headers = calledHeaders(f);
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("x-api-key")).toBeNull();
  });

  it("キャッシュを無効化しタイムアウト用の signal を渡す", async () => {
    const f = mockBackend("{}");
    await GET(request("/api/ai/status"), context(["status"]));
    const init = calledInit(f);
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("クライアントと同じ HTTP メソッドを使う", async () => {
    const f = mockBackend("{}");
    await POST(request("/api/ai/chat", {}, "POST"), context(["chat"]));
    expect(calledInit(f).method).toBe("POST");
  });
});

describe("AI プロキシ — レスポンスの中継", () => {
  it("ステータス・Content-Type・ボディをそのまま返す", async () => {
    mockBackend(JSON.stringify({ sentiment: "bullish" }));
    const res = await GET(request("/api/ai/news/USDJPY"), context(["news", "USDJPY"]));

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("application/json");
    await expect(res.json()).resolves.toEqual({ sentiment: "bullish" });
  });

  it("バックエンドのエラーステータスも維持する", async () => {
    mockBackend(JSON.stringify({ detail: "プラン制限" }), { status: 403 });
    const res = await GET(request("/api/ai/report/USDJPY"), context(["report", "USDJPY"]));

    expect(res.status).toBe(403);
    await expect(res.json()).resolves.toEqual({ detail: "プラン制限" });
  });

  it("Content-Type が無い場合は application/json にフォールバックする", async () => {
    mockBackend("plain", { contentType: null as unknown as string });
    const res = await GET(request("/api/ai/status"), context(["status"]));
    expect(res.headers.get("Content-Type")).toBe("application/json");
  });
});

describe("AI プロキシ — エラーハンドリング", () => {
  it.each([
    ["TimeoutError", Object.assign(new Error("timed out"), { name: "TimeoutError" })],
    ["AbortError", Object.assign(new Error("aborted"), { name: "AbortError" })],
    ["メッセージに timeout を含むエラー", new Error("upstream timeout")],
  ])("%s は 504 として日本語メッセージを返す", async (_name, err) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw err;
      }),
    );

    const res = await GET(request("/api/ai/report/USDJPY"), context(["report", "USDJPY"]));

    expect(res.status).toBe(504);
    const body = (await res.json()) as { detail: string };
    expect(body.detail).toContain("AI分析がタイムアウトしました（120秒）");
  });

  it("接続エラーは 502 として日本語メッセージを返す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const res = await POST(request("/api/ai/chat", {}, "POST"), context(["chat"]));

    expect(res.status).toBe(502);
    const body = (await res.json()) as { detail: string };
    expect(body.detail).toContain("バックエンドに接続できません（502）");
  });
});
