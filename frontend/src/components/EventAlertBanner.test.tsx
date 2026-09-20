/**
 * @file EventAlertBanner.test.tsx
 * @description `EventAlertBanner`（重要経済イベントの警告バナー）のユニットテスト。
 *
 * 検証範囲:
 * - マウント時に 72 時間分のアラートを取得すること
 * - アラート 0 件・取得失敗時は何も描画しないこと
 * - 直近 1 件の内容表示と残り時間の切り上げ
 * - 2 件以上あるときの「他 N 件」表記
 * - カレンダーページへのリンク
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import EventAlertBanner from "./EventAlertBanner";
import * as api from "@/lib/api";
import { eventAlert } from "@/test/fixtures";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

describe("EventAlertBanner — 取得", () => {
  it("マウント時に 72 時間分のアラートを取得する", async () => {
    const spy = vi.spyOn(api, "getEventAlerts").mockResolvedValue({ alerts: [], within_hours: 72 });
    render(<EventAlertBanner />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(72));
  });
});

describe("EventAlertBanner — 非表示条件", () => {
  it("アラートが 0 件なら何も描画しない", async () => {
    vi.spyOn(api, "getEventAlerts").mockResolvedValue({ alerts: [], within_hours: 72 });
    const { container } = render(<EventAlertBanner />);

    await waitFor(() => expect(container.querySelector(".event-alert-banner")).toBeNull());
    expect(container.textContent).toBe("");
  });

  it("取得に失敗しても例外を投げず何も描画しない", async () => {
    vi.spyOn(api, "getEventAlerts").mockRejectedValue(new Error("network"));
    const { container } = render(<EventAlertBanner />);

    await waitFor(() => expect(container.textContent).toBe(""));
  });
});

describe("EventAlertBanner — 表示内容", () => {
  it("直近 1 件のタイトル・国・残り時間を表示する", async () => {
    vi.spyOn(api, "getEventAlerts").mockResolvedValue({
      alerts: [eventAlert({ title: "米国雇用統計", country: "US", hours_until: 5.2 })],
      within_hours: 72,
    });

    render(<EventAlertBanner />);

    // 5.2 時間は切り上げて「6 時間」と表示する
    await waitFor(() =>
      expect(screen.getByText("米国雇用統計（US）— あと約 6 時間")).toBeTruthy(),
    );
    expect(screen.getByText("⚠ 重要イベント間近")).toBeTruthy();
  });

  it("2 件以上あるときは『他 N 件』を添える", async () => {
    vi.spyOn(api, "getEventAlerts").mockResolvedValue({
      alerts: [eventAlert(), eventAlert({ title: "CPI" }), eventAlert({ title: "FOMC" })],
      within_hours: 72,
    });

    render(<EventAlertBanner />);

    await waitFor(() => expect(screen.getByText(/他 2 件/)).toBeTruthy());
  });

  it("1 件のときは『他 N 件』を表示しない", async () => {
    vi.spyOn(api, "getEventAlerts").mockResolvedValue({ alerts: [eventAlert()], within_hours: 72 });

    const { container } = render(<EventAlertBanner />);

    await waitFor(() => expect(container.querySelector(".event-alert-banner")).toBeTruthy());
    expect(container.textContent).not.toContain("他 ");
  });

  it("ファンダメンタルカレンダーへのリンクを表示する", async () => {
    vi.spyOn(api, "getEventAlerts").mockResolvedValue({ alerts: [eventAlert()], within_hours: 72 });

    render(<EventAlertBanner />);

    await waitFor(() => {
      const link = screen.getByText("カレンダー →") as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/fundamental");
    });
  });
});
