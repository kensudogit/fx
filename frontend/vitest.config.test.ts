/**
 * @vitest-environment node
 *
 * @file vitest.config.test.ts
 * @description `vitest.config.ts`（テストランナー設定）自体のユニットテスト。
 *
 * テストスイート全体の前提（jsdom 環境・共通セットアップ・`@` エイリアス・
 * JSX 変換）が失われるとテストが静かに壊れるため、設定内容を明示的に固定する。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect } from "vitest";
import { existsSync } from "fs";
import path from "path";
import config from "./vitest.config";

/** defineConfig の戻り値から test セクションを取り出す */
const test = (config as { test?: Record<string, unknown> }).test ?? {};

/** resolve.alias を取り出す */
const alias = ((config as { resolve?: { alias?: Record<string, string> } }).resolve?.alias ??
  {}) as Record<string, string>;

describe("vitest.config — テスト環境", () => {
  it("DOM を伴うコンポーネントテストのため jsdom を使う", () => {
    expect(test.environment).toBe("jsdom");
  });

  it("describe / it / expect をグローバルに公開する", () => {
    expect(test.globals).toBe(true);
  });

  it("共通セットアップファイルを読み込む", () => {
    expect(test.setupFiles).toEqual(["./src/test/setup.ts"]);
  });

  it("セットアップファイルが実在する", () => {
    expect(existsSync(path.join(process.cwd(), "src/test/setup.ts"))).toBe(true);
  });
});

describe("vitest.config — 対象ファイル", () => {
  it("src 配下のテストとルート直下の設定テストを対象にする", () => {
    expect(test.include).toEqual(["src/**/*.test.{ts,tsx}", "*.test.ts"]);
  });

  it("既定の除外から vitest.config.* を外し、このファイル自身を収集できるようにする", () => {
    const exclude = test.exclude as string[];
    expect(exclude.some((p) => p.includes("vitest"))).toBe(false);
    // 他ツールの設定ファイルは引き続き除外する
    expect(exclude.some((p) => p.includes("webpack"))).toBe(true);
    expect(exclude).toContain("**/node_modules/**");
  });

  it("このテストファイル自体が実行されている（除外設定が効いている証跡）", () => {
    expect(true).toBe(true);
  });
});

describe("vitest.config — 解決設定", () => {
  it("@ エイリアスを src へ解決する", () => {
    expect(alias["@"]).toBe(path.resolve(process.cwd(), "./src"));
  });

  it("tsconfig の jsx: preserve を補うため esbuild で自動ランタイムを指定する", () => {
    const esbuild = (config as { esbuild?: { jsx?: string } }).esbuild;
    expect(esbuild?.jsx).toBe("automatic");
  });
});
