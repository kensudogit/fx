/**
 * @file layout.test.tsx
 * @description `RootLayout`（アプリ全体のルートレイアウト）と
 * メタデータ / ビューポート設定のユニットテスト。
 *
 * ルートレイアウトは `<html>` / `<body>` を返すため、React Testing Library で
 * そのままマウントすると DOM の入れ子が不正になる。ここでは
 * `RootLayout` が返す React 要素ツリーを直接検査し、構造と順序を検証する。
 *
 * 検証範囲:
 * - viewport 設定（デバイス幅・最大ズーム・ノッチ対応・テーマカラー）
 * - metadata 設定（タイトル・説明・PWA マニフェスト・Apple Web App）
 * - html の lang 属性
 * - AuthProvider が全体を包み、NavBar / UsageBanner / main / MobileQuickDock /
 *   UsageGuidePanel がこの順で配置されること
 * - children が main > .container の中に描画されること
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect } from "vitest";
import { isValidElement, type ReactElement } from "react";
import RootLayout, { metadata, viewport } from "./layout";
import { AuthProvider } from "@/context/AuthContext";
import { NavBar } from "@/components/NavBar";
import { UsageBanner } from "@/components/UsageBanner";
import { MobileQuickDock } from "@/components/MobileQuickDock";
import { UsageGuidePanel } from "@/components/UsageGuidePanel";

/** React 要素の children を配列として取り出す */
function childrenOf(el: ReactElement): ReactElement[] {
  const kids = (el.props as { children?: unknown }).children;
  return (Array.isArray(kids) ? kids : [kids]).filter(isValidElement) as ReactElement[];
}

describe("layout — viewport 設定", () => {
  it("モバイル表示に最適化した値を持つ", () => {
    expect(viewport).toEqual({
      width: "device-width",
      initialScale: 1,
      maximumScale: 5,
      viewportFit: "cover",
      themeColor: "#0f1419",
    });
  });

  it("ピンチズームを禁止していない（アクセシビリティ配慮）", () => {
    expect(viewport.maximumScale).toBeGreaterThan(1);
  });
});

describe("layout — metadata 設定", () => {
  it("タイトルと説明を設定する", () => {
    expect(metadata.title).toBe("FX Tool - テクニカル・ファンダメンタル分析");
    expect(metadata.description).toBe(
      "FX通貨ペアのテクニカル分析・ファンダメンタル分析ツール",
    );
  });

  it("PWA マニフェストを参照する", () => {
    expect(metadata.manifest).toBe("/manifest.json");
  });

  it("Apple Web App（ホーム画面追加）に対応する", () => {
    expect(metadata.appleWebApp).toEqual({
      capable: true,
      statusBarStyle: "black-translucent",
      title: "FX Tool",
    });
  });

  it("電話番号の自動リンク変換を無効化する", () => {
    expect(metadata.formatDetection).toEqual({ telephone: false });
  });
});

describe("layout — 要素ツリー", () => {
  /** RootLayout が返すツリーから各階層を取り出す */
  function tree() {
    const html = RootLayout({ children: <p>ページ内容</p> }) as ReactElement;
    const body = childrenOf(html)[0];
    const provider = childrenOf(body)[0];
    return { html, body, provider, providerChildren: childrenOf(provider) };
  }

  it("html の lang を ja にする", () => {
    const { html } = tree();
    expect(html.type).toBe("html");
    expect((html.props as { lang: string }).lang).toBe("ja");
  });

  it("body 直下に AuthProvider を置く", () => {
    const { body, provider } = tree();
    expect(body.type).toBe("body");
    expect(provider.type).toBe(AuthProvider);
  });

  it("共通 UI を NavBar → UsageBanner → main → MobileQuickDock → UsageGuidePanel の順に配置する", () => {
    const { providerChildren } = tree();
    expect(providerChildren.map((c) => c.type)).toEqual([
      NavBar,
      UsageBanner,
      "main",
      MobileQuickDock,
      UsageGuidePanel,
    ]);
  });

  it("children を main > .container の中に描画する", () => {
    const { providerChildren } = tree();
    const main = providerChildren[2];
    const container = childrenOf(main)[0];

    expect((container.props as { className: string }).className).toBe("container");
    expect((container.props as { children: ReactElement }).children).toEqual(<p>ページ内容</p>);
  });
});
