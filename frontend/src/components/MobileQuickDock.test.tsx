/**
 * @file MobileQuickDock.test.tsx
 * @description `MobileQuickDock`（モバイル下部クイックナビ）のユニットテスト。
 *
 * 検証範囲:
 * - 5 つの固定リンク（分析 / 総合 / 自動 / AI / 設定）とアイコンの描画
 * - アクセシビリティ（nav 要素と aria-label）
 * - 現在パスに応じた is-active クラスの付与ルール
 *   （"/" は完全一致、それ以外は前方一致）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MobileQuickDock } from "./MobileQuickDock";

/** usePathname を差し替えて任意のパスを再現する */
const pathname = { current: "/" };
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

// next/link は素の <a> に置き換える（App Router のコンテキストを不要にする）
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/**
 * 指定ラベルのドックアイテム（<a>）を取得する。
 * AI のようにアイコンとラベルが同じ文字列になる項目があるため、
 * `.mobile-dock-label` に限定して検索する。
 */
function item(label: string): HTMLAnchorElement {
  const el = Array.from(document.querySelectorAll(".mobile-dock-label")).find(
    (n) => n.textContent === label,
  );
  if (!el) throw new Error(`ドックアイテムが見つかりません: ${label}`);
  return el.closest("a") as HTMLAnchorElement;
}

describe("MobileQuickDock — 描画", () => {
  it("nav 要素に aria-label を設定する", () => {
    pathname.current = "/";
    render(<MobileQuickDock />);
    expect(screen.getByRole("navigation", { name: "クイックナビ" })).toBeTruthy();
  });

  it("5 つのリンクを正しい遷移先で描画する", () => {
    pathname.current = "/";
    render(<MobileQuickDock />);

    expect(item("分析").getAttribute("href")).toBe("/");
    expect(item("総合").getAttribute("href")).toBe("/analysis");
    expect(item("自動").getAttribute("href")).toBe("/autotrade");
    expect(item("AI").getAttribute("href")).toBe("/ai");
    expect(item("設定").getAttribute("href")).toBe("/settings");
  });

  it("各リンクにアイコン表記を添える", () => {
    pathname.current = "/";
    const { container } = render(<MobileQuickDock />);
    const icons = Array.from(container.querySelectorAll(".mobile-dock-icon")).map(
      (el) => el.textContent,
    );
    expect(icons).toEqual(["FX", "5", "⚡", "AI", "⚙"]);
  });
});

describe("MobileQuickDock — アクティブ判定", () => {
  it('"/" ではトップのみをアクティブにする', () => {
    pathname.current = "/";
    render(<MobileQuickDock />);

    expect(item("分析").className).toContain("is-active");
    expect(item("総合").className).not.toContain("is-active");
  });

  it("他ページでは前方一致でアクティブにする", () => {
    pathname.current = "/analysis";
    render(<MobileQuickDock />);

    expect(item("総合").className).toContain("is-active");
    expect(item("分析").className).not.toContain("is-active");
  });

  it("サブパスでも親リンクをアクティブにする", () => {
    pathname.current = "/autotrade/history";
    render(<MobileQuickDock />);

    expect(item("自動").className).toContain("is-active");
  });

  it("どのリンクにも一致しないパスではアクティブにしない", () => {
    pathname.current = "/pricing";
    const { container } = render(<MobileQuickDock />);

    expect(container.querySelectorAll(".is-active")).toHaveLength(0);
  });
});
