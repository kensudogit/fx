/**
 * @file pricing/page.test.tsx
 * @description `PricingPage`（/pricing）のユニットテスト。
 *
 * 検証範囲:
 * - プラン一覧の取得とカード描画（価格・API 上限の 3 桁区切り・機能フラグ）
 * - Stripe 有効時のみ表示する案内文
 * - Free プランには申込ボタンを出さないこと
 * - 申込ボタンのラベル（Stripe 有効 / ログイン済み / 未ログイン）
 * - 申込時の分岐（未ログイン→/register、Stripe→Checkout、無効→/settings）
 * - 無料登録 CTA のリンク
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PricingPage from "./page";
import * as api from "@/lib/api";
import * as authContext from "@/context/AuthContext";
import { authSession, billingPlan } from "@/test/fixtures";
import { stubLocation } from "@/test/utils";
import type { AuthSession, BillingPlan } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

/** useAuth を差し替える */
function mockAuth(session: AuthSession | null) {
  vi.spyOn(authContext, "useAuth").mockReturnValue({
    saasEnabled: true,
    session,
    loading: false,
    refresh: vi.fn(),
    logout: vi.fn(),
  });
}

/** プラン一覧 API をモックする */
function mockPlans(plans: BillingPlan[], stripeEnabled = false) {
  vi.spyOn(api, "getBillingPlans").mockResolvedValue({ plans, saas_enabled: true, stripe_enabled: stripeEnabled });
}

/** 既定の 2 プラン（Free / Pro） */
function defaultPlans(): BillingPlan[] {
  return [
    billingPlan({
      id: "free",
      name: "Free",
      price_monthly_usd: 0,
      daily_api_limit: 100,
      features: { analysis_basic: true, api_keys: 1 },
    }),
    billingPlan(),
  ];
}

describe("PricingPage — プラン一覧", () => {
  it("取得したプランをカードで表示する", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Free" })).toBeTruthy());
    expect(screen.getByRole("heading", { name: "Pro" })).toBeTruthy();
    expect(document.querySelectorAll(".plan-card")).toHaveLength(2);
  });

  it("月額料金と API 上限（3 桁区切り）を表示する", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByText("$49/月")).toBeTruthy());
    expect(screen.getByText("API 10,000 回/日")).toBeTruthy();
    expect(screen.getByText("$0/月")).toBeTruthy();
  });

  it("有効な機能フラグのみを箇条書きにする", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByText("OpenAI 統合分析")).toBeTruthy());
    expect(screen.getByText("AI Pro（7機能）")).toBeTruthy();
    expect(screen.getByText("自動取引エンジン")).toBeTruthy();
    // Free プランのカードには AI 系の項目が出ない
    const freeCard = document.querySelectorAll(".plan-card")[0];
    expect(freeCard.textContent).not.toContain("OpenAI 統合分析");
  });

  it("API キーの発行可能本数を表示する", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByText("APIキー 5 本")).toBeTruthy());
    expect(screen.getByText("APIキー 1 本")).toBeTruthy();
  });

  it("全プランに共通機能を記載する", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() =>
      expect(screen.getAllByText("テクニカル・ファンダメンタル分析")).toHaveLength(2),
    );
  });

  it("無料登録 CTA を表示する", () => {
    mockAuth(null);
    mockPlans([]);

    render(<PricingPage />);

    expect((screen.getByText("無料で始める") as HTMLAnchorElement).getAttribute("href")).toBe(
      "/register",
    );
  });
});

describe("PricingPage — Stripe の有無", () => {
  it("Stripe 有効時のみ決済案内を表示する", async () => {
    mockAuth(null);
    mockPlans(defaultPlans(), true);

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByText(/Stripe で安全に決済できます/)).toBeTruthy());
  });

  it("Stripe 無効時は決済案内を出さない", async () => {
    mockAuth(null);
    mockPlans(defaultPlans(), false);

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Pro" })).toBeTruthy());
    expect(screen.queryByText(/Stripe で安全に決済できます/)).toBeNull();
  });
});

describe("PricingPage — 申込ボタン", () => {
  it("Free プランには申込ボタンを出さない", async () => {
    mockAuth(null);
    mockPlans(defaultPlans());

    render(<PricingPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Free" })).toBeTruthy());
    expect(document.querySelectorAll(".plan-card button")).toHaveLength(1);
  });

  it.each([
    [true, null, "Stripeで申込"],
    [false, "session", "設定で選択"],
    [false, null, "登録して申込"],
  ])(
    "stripe=%s / session=%s のとき『%s』を表示する",
    async (stripe, session, label) => {
      mockAuth(session ? authSession() : null);
      mockPlans(defaultPlans(), stripe as boolean);

      render(<PricingPage />);

      await waitFor(() => expect(screen.getByRole("button", { name: label })).toBeTruthy());
    },
  );

  it("未ログインなら /register へ誘導する", async () => {
    const location = stubLocation();
    mockAuth(null);
    mockPlans(defaultPlans(), true);

    render(<PricingPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Stripeで申込" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Stripeで申込" }));

    await waitFor(() => expect(location.href).toBe("/register"));
  });

  it("ログイン済み＋Stripe 有効なら Checkout へ遷移する", async () => {
    const location = stubLocation();
    mockAuth(authSession());
    mockPlans(defaultPlans(), true);
    const checkout = vi
      .spyOn(api, "createBillingCheckout")
      .mockResolvedValue({ checkout_url: "https://checkout.stripe.com/s/pro" });

    render(<PricingPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Stripeで申込" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Stripeで申込" }));

    await waitFor(() => expect(checkout).toHaveBeenCalledWith("pro"));
    await waitFor(() => expect(location.href).toBe("https://checkout.stripe.com/s/pro"));
  });

  it("ログイン済み＋Stripe 無効なら /settings へ遷移する", async () => {
    const location = stubLocation();
    mockAuth(authSession());
    mockPlans(defaultPlans(), false);
    const checkout = vi.spyOn(api, "createBillingCheckout");

    render(<PricingPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "設定で選択" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "設定で選択" }));

    await waitFor(() => expect(location.href).toBe("/settings"));
    expect(checkout).not.toHaveBeenCalled();
  });
});
