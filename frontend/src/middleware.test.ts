/**
 * @vitest-environment node
 *
 * @file middleware.test.ts
 * @description `src/middleware.ts`（Next.js Edge Middleware）のユニットテスト。
 *
 * Edge Middleware は `NextRequest` / `NextResponse` を使うため、
 * jsdom ではなく Node 環境（先頭の `@vitest-environment node`）で実行する。
 *
 * 検証範囲:
 * - SaaS モード無効時は全リクエストを素通しすること
 * - パブリックパス（/login・/register・/pricing）とそのサブパスの通過
 * - Cookie の有無による通過・リダイレクトの分岐
 * - リダイレクト先 URL と `from` パラメータ
 * - matcher が静的アセット・API・health を除外していること
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { NextRequest } from "next/server";
import { middleware, config } from "./middleware";

/**
 * テスト用の NextRequest を生成する。
 *
 * @param pathname - アクセスするパス
 * @param token - `fx_access_token` Cookie に設定する値（省略時は Cookie なし）
 */
function request(pathname: string, token?: string): NextRequest {
  const req = new NextRequest(new URL(pathname, "https://fx.example.com"));
  if (token) req.cookies.set("fx_access_token", token);
  return req;
}

describe("middleware — SaaS モード無効時", () => {
  it("認証チェックをせず全リクエストを通過させる", async () => {
    vi.stubEnv("NEXT_PUBLIC_SAAS_ENABLED", "false");
    vi.resetModules();
    const { middleware: mw } = await import("./middleware");

    const res = mw(request("/settings"));

    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });
});

describe("middleware — パブリックパス", () => {
  it.each(["/login", "/register", "/pricing"])("%s は認証なしで通過できる", (path) => {
    const res = middleware(request(path));
    expect(res.headers.get("location")).toBeNull();
  });

  it.each(["/login/callback", "/register/complete", "/pricing/enterprise"])(
    "%s のようなサブパスも通過できる",
    (path) => {
      const res = middleware(request(path));
      expect(res.headers.get("location")).toBeNull();
    },
  );

  it("パブリックパスの前方一致だけでは通過させない（/loginx はリダイレクト）", () => {
    const res = middleware(request("/loginx"));
    expect(res.headers.get("location")).toContain("/login");
  });
});

describe("middleware — 保護されたパス", () => {
  it("トークンが無い場合は /login へリダイレクトする", () => {
    const res = middleware(request("/settings"));

    expect(res.status).toBe(307);
    const location = new URL(res.headers.get("location") as string);
    expect(location.pathname).toBe("/login");
  });

  it("リダイレクト時は from パラメータに元のパスを渡す", () => {
    const res = middleware(request("/autotrade"));
    const location = new URL(res.headers.get("location") as string);
    expect(location.searchParams.get("from")).toBe("/autotrade");
  });

  it("トークンがある場合はそのまま通過させる", () => {
    const res = middleware(request("/settings", "jwt-abc"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("トークンの有効性は検証しない（任意の文字列でも通過する）", () => {
    const res = middleware(request("/dashboard", "not-a-real-jwt"));
    expect(res.headers.get("location")).toBeNull();
  });

  it("ルート（/）も保護対象で未認証ならリダイレクトされる", () => {
    const res = middleware(request("/"));
    const location = new URL(res.headers.get("location") as string);
    expect(location.searchParams.get("from")).toBe("/");
  });
});

describe("middleware — matcher 設定", () => {
  /** matcher の正規表現に対してパスが一致するか判定する */
  const matches = (path: string) => new RegExp(`^${config.matcher[0]}$`).test(path);

  it("matcher は 1 パターンのみ定義されている", () => {
    expect(config.matcher).toHaveLength(1);
  });

  it.each(["/_next/static/chunk.js", "/_next/image", "/favicon.ico", "/api/symbols", "/health"])(
    "%s はミドルウェアをバイパスする",
    (path) => {
      expect(matches(path)).toBe(false);
    },
  );

  it.each(["/", "/settings", "/autotrade", "/login"])("%s はミドルウェアの対象になる", (path) => {
    expect(matches(path)).toBe(true);
  });
});
