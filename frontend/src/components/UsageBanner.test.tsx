/**
 * @file UsageBanner.test.tsx
 * @description `UsageBanner`（API 利用量の警告バナー）のユニットテスト。
 *
 * 検証範囲:
 * - 非表示条件（読み込み中・未ログイン・有料プランかつ利用量 ok）
 * - 利用レベル（ok / warning / critical / exhausted）ごとの見出しとクラス
 * - usage_level が無い場合に利用率からレベルを算出すること
 * - 利用回数の 3 桁区切り表示とゲージ幅（100% で頭打ち）
 * - アップグレードボタン（Stripe 成功時のリダイレクト・失敗時の /pricing フォールバック）
 * - 設定ページへのリンク
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UsageBanner } from "./UsageBanner";
import * as authContext from "@/context/AuthContext";
import * as api from "@/lib/api";
import { authSession } from "@/test/fixtures";
import { stubLocation } from "@/test/utils";
import type { AuthSession } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/** useAuth を差し替える */
function mockAuth(session: AuthSession | null, loading = false) {
  vi.spyOn(authContext, "useAuth").mockReturnValue({
    saasEnabled: true,
    session,
    loading,
    refresh: vi.fn(),
    logout: vi.fn(),
  });
}

/** 利用量とプランを指定したセッションを組み立てる */
function sessionWith(
  usage: Partial<AuthSession["usage"]>,
  plan = "pro",
): AuthSession {
  return authSession({
    tenant: { id: 1, name: "Example", slug: "example", plan },
    usage: {
      daily_calls: 0,
      daily_limit: 1000,
      remaining: 1000,
      ...usage,
    } as AuthSession["usage"],
  });
}

describe("UsageBanner — 非表示条件", () => {
  it("読み込み中は描画しない", () => {
    mockAuth(null, true);
    const { container } = render(<UsageBanner />);
    expect(container.textContent).toBe("");
  });

  it("未ログイン時は描画しない", () => {
    mockAuth(null);
    const { container } = render(<UsageBanner />);
    expect(container.textContent).toBe("");
  });

  it("有料プランかつ利用量が ok なら描画しない", () => {
    mockAuth(sessionWith({ usage_level: "ok" }, "pro"));
    const { container } = render(<UsageBanner />);
    expect(container.textContent).toBe("");
  });

  it("Free プランなら利用量が ok でも常に描画する", () => {
    mockAuth(sessionWith({ usage_level: "ok" }, "free"));
    render(<UsageBanner />);
    expect(screen.getByText("FREE プラン")).toBeTruthy();
  });
});

describe("UsageBanner — 利用レベルの表示", () => {
  it.each([
    ["warning", "API 利用量が増えています"],
    ["critical", "API 利用量が上限に近づいています"],
    ["exhausted", "本日の API 上限に達しました"],
  ])("usage_level=%s では『%s』を表示する", (level, message) => {
    mockAuth(sessionWith({ usage_level: level as AuthSession["usage"]["usage_level"] }, "pro"));

    const { container } = render(<UsageBanner />);

    expect(screen.getByText(message)).toBeTruthy();
    expect(container.querySelector(`.usage-banner--${level}`)).toBeTruthy();
  });

  it("usage_level が無い場合は利用率 90% 以上を critical と判定する", () => {
    mockAuth(sessionWith({ daily_calls: 950, daily_limit: 1000, usage_percent: undefined }, "pro"));

    render(<UsageBanner />);

    expect(screen.getByText("API 利用量が上限に近づいています")).toBeTruthy();
  });

  it("usage_level が無い場合は利用率 75〜89% を warning と判定する", () => {
    mockAuth(sessionWith({ daily_calls: 800, daily_limit: 1000, usage_percent: undefined }, "pro"));

    render(<UsageBanner />);

    expect(screen.getByText("API 利用量が増えています")).toBeTruthy();
  });

  it("usage_percent が指定されていればそちらを優先する", () => {
    mockAuth(
      sessionWith({ daily_calls: 10, daily_limit: 1000, usage_percent: 95, usage_level: undefined }, "pro"),
    );

    render(<UsageBanner />);

    expect(screen.getByText("API 利用量が上限に近づいています")).toBeTruthy();
  });
});

describe("UsageBanner — 利用量の表示", () => {
  it("利用回数と上限を 3 桁区切りで表示する", () => {
    mockAuth(sessionWith({ daily_calls: 12345, daily_limit: 100000, usage_level: "warning" }));

    render(<UsageBanner />);

    expect(screen.getByText("12,345 / 100,000 回")).toBeTruthy();
  });

  it("ゲージ幅は利用率に比例する", () => {
    mockAuth(sessionWith({ usage_percent: 42, usage_level: "warning" }));

    const { container } = render(<UsageBanner />);

    expect((container.querySelector(".usage-bar-fill") as HTMLElement).style.width).toBe("42%");
  });

  it("利用率が 100% を超えてもゲージは 100% で頭打ちにする", () => {
    mockAuth(sessionWith({ usage_percent: 150, usage_level: "exhausted" }));

    const { container } = render(<UsageBanner />);

    expect((container.querySelector(".usage-bar-fill") as HTMLElement).style.width).toBe("100%");
  });
});

describe("UsageBanner — アップグレード導線", () => {
  it("Stripe Checkout の URL を取得してリダイレクトする", async () => {
    const location = stubLocation();
    mockAuth(sessionWith({ usage_level: "critical" }));
    vi.spyOn(api, "createBillingCheckout").mockResolvedValue({
      checkout_url: "https://checkout.stripe.com/s/1",
    });

    render(<UsageBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Pro にアップグレード" }));

    await waitFor(() => expect(location.href).toBe("https://checkout.stripe.com/s/1"));
    expect(api.createBillingCheckout).toHaveBeenCalledWith("pro");
  });

  it("Checkout に失敗した場合は /pricing へフォールバックする", async () => {
    const location = stubLocation();
    mockAuth(sessionWith({ usage_level: "critical" }));
    vi.spyOn(api, "createBillingCheckout").mockRejectedValue(new Error("Stripe 未設定"));

    render(<UsageBanner />);
    fireEvent.click(screen.getByRole("button", { name: "Pro にアップグレード" }));

    await waitFor(() => expect(location.href).toBe("/pricing"));
  });

  it("設定ページへのリンクを表示する", () => {
    mockAuth(sessionWith({ usage_level: "warning" }));

    render(<UsageBanner />);

    expect((screen.getByText("設定") as HTMLAnchorElement).getAttribute("href")).toBe("/settings");
  });
});
