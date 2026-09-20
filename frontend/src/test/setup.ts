/**
 * @file src/test/setup.ts
 * @description 全テスト共通のセットアップ（vitest.config.ts の `setupFiles` から読み込まれる）。
 *
 * 役割:
 * - 各テスト後に React Testing Library のマウント済み DOM を破棄する。
 * - jsdom が実装していないブラウザ API（matchMedia / ResizeObserver /
 *   scrollIntoView / PointerCapture / URL.createObjectURL）をスタブ化する。
 *   これらが未定義だと recharts・AIProDashboard・UsageGuidePanel 等が例外を投げる。
 * - localStorage / document.cookie / モックをテストごとにリセットし、
 *   テスト間で状態が漏れないようにする。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * jsdom 未実装の `window.matchMedia` をスタブ化する。
 * レスポンシブ分岐を持つコンポーネントが参照する。
 */
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

/**
 * jsdom 未実装の `ResizeObserver` をスタブ化する。
 * recharts の ResponsiveContainer が内部で利用する。
 */
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (typeof Element !== "undefined") {
  /** jsdom 未実装の `scrollIntoView`（AIProDashboard のチャット自動スクロール）*/
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
  /** jsdom 未実装の Pointer Capture API（UsageGuidePanel のドラッグ処理）*/
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {};
    Element.prototype.releasePointerCapture = () => {};
    Element.prototype.hasPointerCapture = () => false;
  }
}

/**
 * jsdom 未実装の `PointerEvent` を MouseEvent ベースで補う。
 *
 * これが無いと Testing Library の `fireEvent.pointerDown/Move` が素の `Event` に
 * フォールバックし、`clientX` / `pointerId` が渡らないため
 * UsageGuidePanel のドラッグ処理をテストできない。
 */
if (typeof window !== "undefined" && typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    pointerId: number;
    pointerType: string;
    isPrimary: boolean;

    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
      this.pointerId = params.pointerId ?? 0;
      this.pointerType = params.pointerType ?? "mouse";
      this.isPrimary = params.isPrimary ?? true;
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent;
  globalThis.PointerEvent = window.PointerEvent;
}

/**
 * jsdom 未実装の `URL.createObjectURL` / `revokeObjectURL`。
 * `openChartImage()` が Blob URL を生成するために使用する。
 */
if (typeof URL !== "undefined" && !URL.createObjectURL) {
  URL.createObjectURL = () => "blob:mock";
  URL.revokeObjectURL = () => {};
}

beforeEach(() => {
  // localStorage をテストごとに空にする（認証トークン等の持ち越しを防ぐ）
  if (typeof localStorage !== "undefined") localStorage.clear();
  // Cookie もクリアする（setAccessToken が書き込む fx_access_token など）
  if (typeof document !== "undefined") {
    for (const c of document.cookie.split(";")) {
      const name = c.split("=")[0]?.trim();
      if (name) document.cookie = `${name}=; path=/; max-age=0`;
    }
  }
});

afterEach(() => {
  // レンダリング済みコンポーネントをアンマウントして DOM を初期化する
  cleanup();
  // vi.fn() / vi.spyOn() の呼び出し履歴と実装をリセットする
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
