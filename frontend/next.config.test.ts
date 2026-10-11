/**
 * @vitest-environment node
 *
 * @file next.config.test.ts
 * @description `next.config.ts`（Next.js 設定）のユニットテスト。
 *
 * 検証範囲:
 * - outputFileTracingRoot がプロジェクトルートを指すこと
 * - rewrites が 4 経路（/api/**・/health・/docs・/openapi.json）を定義すること
 * - 転送先バックエンドの解決優先順位
 *   （INTERNAL_API_URL > 本番の 127.0.0.1 > 開発の localhost）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import path from "path";
import nextConfig from "./next.config";

/** 環境変数を差し替えたうえで設定モジュールを読み直す */
async function loadConfig(env: Record<string, string | undefined>) {
  for (const [key, value] of Object.entries(env)) {
    // undefined を渡した場合は「未設定」を再現する
    vi.stubEnv(key, value as string);
  }
  vi.resetModules();
  const mod = await import("./next.config");
  return mod.default;
}

/** rewrites を source→destination のマップとして取り出す */
async function rewriteMap(config: typeof nextConfig): Promise<Record<string, string>> {
  const rules = await config.rewrites!();
  const list = Array.isArray(rules) ? rules : (rules.beforeFiles ?? []);
  return Object.fromEntries(list.map((r) => [r.source, r.destination]));
}

describe("next.config — 基本設定", () => {
  it("outputFileTracingRoot をプロジェクトルートに設定する", () => {
    expect(nextConfig.outputFileTracingRoot).toBe(path.join(process.cwd()));
  });

  it("rewrites を非同期関数として定義する", () => {
    expect(typeof nextConfig.rewrites).toBe("function");
  });
});

describe("next.config — rewrites", () => {
  it("4 つの転送ルールを定義する", async () => {
    const map = await rewriteMap(nextConfig);
    expect(Object.keys(map)).toEqual(["/api/:path*", "/health", "/docs", "/openapi.json"]);
  });

  it("/api/:path* をバックエンドの同じパスへ転送する", async () => {
    const map = await rewriteMap(nextConfig);
    expect(map["/api/:path*"]).toMatch(/\/api\/:path\*$/);
  });

  it("ヘルスチェック・Swagger・OpenAPI をバックエンドへ転送する", async () => {
    const map = await rewriteMap(nextConfig);
    expect(map["/health"]).toMatch(/\/health$/);
    expect(map["/docs"]).toMatch(/\/docs$/);
    expect(map["/openapi.json"]).toMatch(/\/openapi\.json$/);
  });
});

describe("next.config — バックエンド URL の解決", () => {
  it("INTERNAL_API_URL が最優先される", async () => {
    const config = await loadConfig({
      INTERNAL_API_URL: "http://backend.railway.internal:8000",
      NODE_ENV: "production",
    });

    const map = await rewriteMap(config);
    expect(map["/health"]).toBe("http://backend.railway.internal:8000/health");
  });

  it("本番環境では 127.0.0.1:8000 を使う", async () => {
    const config = await loadConfig({ INTERNAL_API_URL: "", NODE_ENV: "production" });

    const map = await rewriteMap(config);
    expect(map["/health"]).toBe("http://127.0.0.1:8000/health");
  });

  it("開発環境では localhost:8000 を使う", async () => {
    const config = await loadConfig({ INTERNAL_API_URL: "", NODE_ENV: "development" });

    const map = await rewriteMap(config);
    expect(map["/health"]).toBe("http://localhost:8000/health");
  });
});
