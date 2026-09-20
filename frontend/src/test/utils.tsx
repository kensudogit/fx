/**
 * @file src/test/utils.tsx
 * @description テスト共通のユーティリティ群。
 *
 * - `mockFetchOnce` / `mockFetchJson` — `global.fetch` をモックしてレスポンスを差し替える。
 * - `stubLocation` — `window.location.href` への代入を検証可能にする。
 * - `flush` — pending な Promise を消化して React の状態更新を確定させる。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { act } from "@testing-library/react";
import { vi, type Mock } from "vitest";

/**
 * `fetch` の戻り値として使える最小限の Response ライクなオブジェクトを生成する。
 *
 * @param body - `res.json()` が返すボディ。`undefined` の場合は json() が例外を投げる
 *               （JSON でないエラーレスポンスの再現に使う）
 * @param init - ステータス・statusText・blob の上書き
 */
export function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number; statusText?: string; blob?: Blob } = {},
) {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? status < 400,
    status,
    statusText: init.statusText ?? "",
    json: async () => {
      if (body === undefined) throw new SyntaxError("Unexpected token");
      return body;
    },
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
    blob: async () => init.blob ?? new Blob(["x"]),
    headers: new Headers({ "content-type": "application/json" }),
  } as unknown as Response;
}

/**
 * `global.fetch` を vi.fn() へ差し替える。
 *
 * @param impl - 呼び出しごとの実装。省略時は常に `{}` を返す。
 * @returns 差し替えたモック関数（呼び出し引数の検証に使う）
 */
export function mockFetch(impl?: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    return impl ? impl(url, init) : jsonResponse({});
  });
  vi.stubGlobal("fetch", fn);
  return fn as unknown as Mock;
}

/**
 * URL パスの部分一致でレスポンスを切り替える fetch モックを作る。
 *
 * @param routes - パスの部分文字列をキー、レスポンスボディを値とするマップ
 * @param fallback - どのキーにも一致しなかった場合のボディ（既定は `{}`）
 */
export function mockFetchRoutes(routes: Record<string, unknown>, fallback: unknown = {}) {
  return mockFetch((url) => {
    for (const [key, body] of Object.entries(routes)) {
      if (url.includes(key)) return jsonResponse(body);
    }
    return jsonResponse(fallback);
  });
}

/**
 * `window.location` を書き込み可能なスタブへ差し替える。
 *
 * jsdom の `location.href` への代入は "Not implemented: navigation" 警告を出すため、
 * リダイレクトを検証したいテストではこのスタブを使う。
 *
 * @param initialHref - 初期 URL
 * @returns 代入された href を保持するオブジェクト
 */
export function stubLocation(initialHref = "http://localhost/") {
  const url = new URL(initialHref);
  const loc = {
    href: initialHref,
    pathname: url.pathname,
    search: url.search,
    host: url.host,
    protocol: url.protocol,
    assign: vi.fn(),
    replace: vi.fn(),
    reload: vi.fn(),
  };
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: loc,
  });
  return loc;
}

/**
 * マイクロタスクキューを消化して、useEffect 内の非同期処理を確定させる。
 *
 * `await flush()` で `.then()` チェーンの結果が state に反映される。
 */
export async function flush(times = 3) {
  for (let i = 0; i < times; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await Promise.resolve();
    });
  }
}
