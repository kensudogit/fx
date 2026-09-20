/**
 * @file page.test.tsx
 * @description `Home`（トップページ — テクニカル分析ダッシュボード）のユニットテスト。
 *
 * このページは描画を TechnicalDashboard に全面委譲する薄いラッパーのため、
 * 「委譲先を正しく 1 つだけ描画するか」を検証する。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Page from "./page";

// 委譲先はスタブ化し、ページ自身の責務（委譲）だけを検証する
vi.mock("@/components/TechnicalDashboard", () => ({
  default: () => <div data-testid="delegate">TechnicalDashboard</div>,
}));

describe("Home (/)", () => {
  it("TechnicalDashboard を描画する", () => {
    render(<Page />);
    expect(screen.getByTestId("delegate").textContent).toBe("TechnicalDashboard");
  });

  it("委譲先は 1 つだけ描画する", () => {
    render(<Page />);
    expect(screen.getAllByTestId("delegate")).toHaveLength(1);
  });

  it("ページ自身は追加のマークアップを持たない", () => {
    const { container } = render(<Page />);
    expect(container.children).toHaveLength(1);
  });

  it("デフォルトエクスポートが関数コンポーネントである", () => {
    expect(typeof Page).toBe("function");
    expect(Page.name).toBe("Home");
  });
});
