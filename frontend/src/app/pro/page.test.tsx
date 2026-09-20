/**
 * @file pro/page.test.tsx
 * @description `ProPage`（AI Pro ダッシュボードページ）のユニットテスト。
 *
 * このページは描画を AIProDashboard に全面委譲する薄いラッパーのため、
 * 「委譲先を正しく 1 つだけ描画するか」を検証する。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Page from "./page";

// 委譲先はスタブ化し、ページ自身の責務（委譲）だけを検証する
vi.mock("@/components/AIProDashboard", () => ({
  default: () => <div data-testid="delegate">AIProDashboard</div>,
}));

describe("ProPage (/pro)", () => {
  it("AIProDashboard を描画する", () => {
    render(<Page />);
    expect(screen.getByTestId("delegate").textContent).toBe("AIProDashboard");
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
    expect(Page.name).toBe("ProPage");
  });
});
