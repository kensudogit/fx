/**
 * @file autotrade/page.test.tsx
 * @description `AutoTradePage`（自動取引ページ）のユニットテスト。
 *
 * このページは描画を AutoTradePanel に全面委譲する薄いラッパーのため、
 * 「委譲先を正しく 1 つだけ描画するか」を検証する。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Page from "./page";

// 委譲先はスタブ化し、ページ自身の責務（委譲）だけを検証する
vi.mock("@/components/AutoTradePanel", () => ({
  default: () => <div data-testid="delegate">AutoTradePanel</div>,
}));

describe("AutoTradePage (/autotrade)", () => {
  it("AutoTradePanel を描画する", () => {
    render(<Page />);
    expect(screen.getByTestId("delegate").textContent).toBe("AutoTradePanel");
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
    expect(Page.name).toBe("AutoTradePage");
  });
});
