/**
 * Vitest 設定 — FX トレード支援プラットフォーム（フロントエンド）
 *
 * - environment: jsdom — React コンポーネントを DOM 付きでレンダリングする。
 *   Route Handler / Middleware のテストはファイル先頭の `@vitest-environment node`
 *   ドキュメントコメントで Node 環境に切り替える。
 * - globals: true — describe / it / expect をインポートなしでも利用できるようにする。
 * - setupFiles — 全テスト共通の初期化（DOM クリーンアップ・jsdom 未実装 API の
 *   スタブ・localStorage リセットなど）を `src/test/setup.ts` で行う。
 * - esbuild.jsx: "automatic" — tsconfig の `jsx: "preserve"`（Next.js 用）では
 *   esbuild が JSX を変換できないため、テスト時のみ自動ランタイムを指定する。
 */

import { defineConfig, configDefaults } from "vitest/config";
import path from "path";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "*.test.ts"],
    // 既定の除外パターンは `**/{...,vitest,...}.config.*` を含むため、
    // `vitest.config.test.ts`（本設定自体のテスト）まで除外されてしまう。
    // vitest を含む既定パターンを外し、他ツールの設定ファイルだけを除外する。
    exclude: [
      ...configDefaults.exclude.filter((pattern) => !pattern.includes("vitest")),
      "**/{karma,rollup,webpack,vite,jest,ava,babel,nyc,cypress,tsup,build,eslint,prettier}.config.*",
    ],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
