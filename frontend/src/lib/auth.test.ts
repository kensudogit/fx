/**
 * @file auth.test.ts
 * @description `src/lib/auth.ts`（認証トークン管理）のユニットテスト。
 *
 * 検証範囲:
 * - JWT アクセストークンの localStorage + Cookie 双方への保存・取得
 * - API キーの localStorage 保存（Cookie には書かないこと）
 * - clearAuth() による両方の削除と Cookie の即時失効
 * - authHeaders() の優先順位（JWT > API キー > 認証なし）
 * - SAAS_ENABLED の環境変数による決定ロジック
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  authHeaders,
  clearAuth,
  getAccessToken,
  getApiKey,
  setAccessToken,
  setApiKey,
  SAAS_ENABLED,
} from "./auth";

/** localStorage のキー名（実装と同じ値。変更を検知するためテスト側にも定義する） */
const TOKEN_KEY = "fx_access_token";
const API_KEY_KEY = "fx_api_key";

describe("auth — アクセストークン", () => {
  it("未保存の場合 getAccessToken は null を返す", () => {
    expect(getAccessToken()).toBeNull();
  });

  it("setAccessToken が localStorage に保存し getAccessToken で読み出せる", () => {
    setAccessToken("jwt-abc");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("jwt-abc");
    expect(getAccessToken()).toBe("jwt-abc");
  });

  it("setAccessToken は Middleware 用に Cookie へも書き込む", () => {
    setAccessToken("jwt-abc");
    expect(document.cookie).toContain("fx_access_token=jwt-abc");
  });

  it("Cookie 値は URL エンコードされる", () => {
    setAccessToken("a b+c/d");
    expect(document.cookie).toContain(`fx_access_token=${encodeURIComponent("a b+c/d")}`);
  });

  it("Cookie には path / max-age(72時間) / SameSite=Lax が付与される", () => {
    // jsdom の document.cookie は属性を読み戻せないため、setter への代入文字列を捕捉する
    const spy = vi.spyOn(document, "cookie", "set");
    setAccessToken("jwt-abc");
    const written = spy.mock.calls[0][0];
    expect(written).toContain("path=/");
    expect(written).toContain(`max-age=${72 * 3600}`);
    expect(written).toContain("SameSite=Lax");
    // クライアント JS から読む必要があるため HttpOnly は付与しない
    expect(written).not.toContain("HttpOnly");
  });
});

describe("auth — API キー", () => {
  it("未保存の場合 getApiKey は null を返す", () => {
    expect(getApiKey()).toBeNull();
  });

  it("setApiKey は localStorage にのみ保存し Cookie には書かない", () => {
    setApiKey("fx_live_123");
    expect(localStorage.getItem(API_KEY_KEY)).toBe("fx_live_123");
    expect(getApiKey()).toBe("fx_live_123");
    expect(document.cookie).not.toContain("fx_api_key");
  });
});

describe("auth — clearAuth", () => {
  it("JWT・API キー・Cookie をすべて削除する", () => {
    setAccessToken("jwt-abc");
    setApiKey("fx_live_123");

    clearAuth();

    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(API_KEY_KEY)).toBeNull();
    expect(document.cookie).not.toContain("jwt-abc");
  });

  it("Cookie は max-age=0 で即時失効させる", () => {
    const spy = vi.spyOn(document, "cookie", "set");
    clearAuth();
    expect(spy.mock.calls.at(-1)?.[0]).toContain("max-age=0");
  });
});

describe("auth — authHeaders", () => {
  it("認証情報が無い場合は空オブジェクトを返す", () => {
    expect(authHeaders()).toEqual({});
  });

  it("JWT がある場合は Authorization: Bearer を返す", () => {
    setAccessToken("jwt-abc");
    expect(authHeaders()).toEqual({ Authorization: "Bearer jwt-abc" });
  });

  it("JWT が無く API キーがある場合は X-API-Key を返す", () => {
    setApiKey("fx_live_123");
    expect(authHeaders()).toEqual({ "X-API-Key": "fx_live_123" });
  });

  it("両方ある場合は JWT を優先する", () => {
    setAccessToken("jwt-abc");
    setApiKey("fx_live_123");
    expect(authHeaders()).toEqual({ Authorization: "Bearer jwt-abc" });
    expect(authHeaders()).not.toHaveProperty("X-API-Key");
  });
});

describe("auth — SAAS_ENABLED", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("環境変数が未設定ならデフォルトで有効（true）", () => {
    // 本テストファイルの実行環境では NEXT_PUBLIC_SAAS_ENABLED は未設定
    expect(SAAS_ENABLED).toBe(true);
  });

  it('NEXT_PUBLIC_SAAS_ENABLED="false" のときだけ無効になる', async () => {
    vi.stubEnv("NEXT_PUBLIC_SAAS_ENABLED", "false");
    vi.resetModules();
    const mod = await import("./auth");
    expect(mod.SAAS_ENABLED).toBe(false);
  });

  it('"true" 以外の任意の値（例 "1"）でも有効のまま', async () => {
    vi.stubEnv("NEXT_PUBLIC_SAAS_ENABLED", "1");
    vi.resetModules();
    const mod = await import("./auth");
    expect(mod.SAAS_ENABLED).toBe(true);
  });
});

describe("auth — SSR（window 未定義）", () => {
  let originalWindow: typeof globalThis.window;

  beforeEach(() => {
    originalWindow = globalThis.window;
  });

  afterEach(() => {
    globalThis.window = originalWindow;
  });

  it("window が無い環境では getAccessToken / getApiKey が null を返す", () => {
    setAccessToken("jwt-abc");
    setApiKey("fx_live_123");

    // サーバーサイドレンダリングを再現する
    // @ts-expect-error — テストのため意図的に window を削除する
    delete globalThis.window;

    expect(getAccessToken()).toBeNull();
    expect(getApiKey()).toBeNull();
    expect(authHeaders()).toEqual({});
  });
});
