/**
 * @file settings/page.test.tsx
 * @description `SettingsPage`（/settings）のユニットテスト。
 *
 * 検証範囲:
 * - 未ログイン時のローディング表示
 * - 初期ロード（プラン一覧・API キー一覧・OANDA 設定）と失敗時の握りつぶし
 * - ワークスペース情報（テナント・プラン・Stripe 契約バッジ・利用量メーター）
 * - Stripe 請求ポータル（表示条件・遷移・失敗時のエラー）
 * - プラン変更（Stripe Checkout / 直接アップグレード・現在プランはボタン非表示）
 * - OANDA 設定の保存（トークン未入力時は送らない・保存後の再取得・失敗時のエラー）
 * - API キー発行（平文の一度きり表示・ブラウザ保存・一覧の更新・失敗時のエラー）
 * - Stripe 決済成功時のクエリ処理
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SettingsPage from "./page";
import * as api from "@/lib/api";
import * as auth from "@/lib/auth";
import * as authContext from "@/context/AuthContext";
import { authSession, billingPlan } from "@/test/fixtures";
import { stubLocation } from "@/test/utils";
import type { AuthSession } from "@/lib/api";

/** useAuth を差し替える */
function mockAuth(session: AuthSession | null) {
  const refresh = vi.fn().mockResolvedValue(undefined);
  vi.spyOn(authContext, "useAuth").mockReturnValue({
    saasEnabled: true,
    session,
    loading: false,
    refresh,
    logout: vi.fn(),
  });
  return { refresh };
}

/** OANDA 設定 API のレスポンス型 */
type OandaSettings = Awaited<ReturnType<typeof api.getOandaSettings>>;

/** 初期ロード系 API をモックする */
function mockApis(opts: { stripeEnabled?: boolean; oanda?: Partial<OandaSettings> } = {}) {
  vi.spyOn(api, "getBillingPlans").mockResolvedValue({
    plans: [
      billingPlan({ id: "free", name: "Free", price_monthly_usd: 0, daily_api_limit: 100, features: {} }),
      billingPlan(),
    ],
    saas_enabled: true,
    stripe_enabled: opts.stripeEnabled ?? false,
  });
  vi.spyOn(api, "listApiKeys").mockResolvedValue({
    keys: [
      { id: 1, name: "TradingView Webhook", key_prefix: "fx_abc", created_at: "2026-01-01T00:00:00Z" },
    ],
  });
  vi.spyOn(api, "getOandaSettings").mockResolvedValue({
    settings: { account_id: "101-001-123", environment: "practice" },
    account_summary: { configured: false, message: "OANDA トークン未設定" },
    ...opts.oanda,
  } as OandaSettings);
}

/** 読み込み完了を待つ */
async function waitLoaded() {
  await waitFor(() => expect(screen.getByRole("heading", { name: "設定・課金" })).toBeTruthy());
}

/** ラベルから入力要素を取得する */
function field(label: string): HTMLElement {
  return screen.getByLabelText(label);
}

describe("SettingsPage — 未ログイン", () => {
  it("セッションが無い間はローディング表示にする", () => {
    mockAuth(null);
    mockApis();

    render(<SettingsPage />);

    expect(screen.getByText("読み込み中...")).toBeTruthy();
  });
});

describe("SettingsPage — ワークスペース", () => {
  it("テナント名・スラッグ・プラン・ログインメールを表示する", async () => {
    mockAuth(authSession());
    mockApis();

    render(<SettingsPage />);
    await waitLoaded();

    expect(screen.getByText("Example 株式会社")).toBeTruthy();
    // テナント名とスラッグは同じ段落に描画される
    expect(screen.getByText("Example 株式会社").closest("p")?.textContent).toBe(
      "Example 株式会社（example）",
    );
    expect(screen.getByText("FREE")).toBeTruthy();
    expect(screen.getByText("ログイン: trader@example.com")).toBeTruthy();
  });

  it("usage_percent があればそれを利用率に使う", async () => {
    mockAuth(
      authSession({
        usage: { daily_calls: 40, daily_limit: 100, remaining: 60, usage_percent: 37 },
      }),
    );
    mockApis();

    const { container } = render(<SettingsPage />);
    await waitLoaded();

    expect(screen.getByText("本日の API 利用 (37%)")).toBeTruthy();
    expect((container.querySelector(".usage-bar-fill") as HTMLElement).style.width).toBe("37%");
  });

  it("usage_percent が無ければ利用回数から算出する", async () => {
    mockAuth(
      authSession({
        usage: { daily_calls: 25, daily_limit: 100, remaining: 75, usage_percent: undefined },
      }),
    );
    mockApis();

    render(<SettingsPage />);
    await waitLoaded();

    expect(screen.getByText("本日の API 利用 (25%)")).toBeTruthy();
  });

  it("利用率が 100% を超えてもゲージは頭打ちにする", async () => {
    mockAuth(
      authSession({
        usage: { daily_calls: 150, daily_limit: 100, remaining: 0, usage_percent: 150 },
      }),
    );
    mockApis();

    const { container } = render(<SettingsPage />);
    await waitLoaded();

    expect((container.querySelector(".usage-bar-fill") as HTMLElement).style.width).toBe("100%");
  });

  it("Stripe 契約中ならバッジを表示する", async () => {
    mockAuth(
      authSession({ billing: { stripe_customer: true, stripe_subscription: true } }),
    );
    mockApis();

    render(<SettingsPage />);
    await waitLoaded();

    expect(screen.getByText("Stripe契約中")).toBeTruthy();
  });
});

describe("SettingsPage — Stripe 請求ポータル", () => {
  it("Stripe 有効かつ顧客登録済みのときだけボタンを出す", async () => {
    mockAuth(authSession({ billing: { stripe_customer: true, stripe_subscription: false } }));
    mockApis({ stripeEnabled: true });

    render(<SettingsPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stripe 請求ポータル" })).toBeTruthy(),
    );
  });

  it("Stripe 無効ならボタンを出さない", async () => {
    mockAuth(authSession({ billing: { stripe_customer: true, stripe_subscription: false } }));
    mockApis({ stripeEnabled: false });

    render(<SettingsPage />);
    await waitLoaded();

    expect(screen.queryByRole("button", { name: "Stripe 請求ポータル" })).toBeNull();
  });

  it("ポータル URL を取得して遷移する", async () => {
    const location = stubLocation();
    mockAuth(authSession({ billing: { stripe_customer: true, stripe_subscription: true } }));
    mockApis({ stripeEnabled: true });
    vi.spyOn(api, "createBillingPortal").mockResolvedValue({
      portal_url: "https://billing.stripe.com/p/1",
    });

    render(<SettingsPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stripe 請求ポータル" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Stripe 請求ポータル" }));

    await waitFor(() => expect(location.href).toBe("https://billing.stripe.com/p/1"));
  });

  it("ポータルの取得に失敗したらエラーを表示する", async () => {
    stubLocation();
    mockAuth(authSession({ billing: { stripe_customer: true, stripe_subscription: true } }));
    mockApis({ stripeEnabled: true });
    vi.spyOn(api, "createBillingPortal").mockRejectedValue(new Error("Stripe 顧客が未作成です"));

    render(<SettingsPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stripe 請求ポータル" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Stripe 請求ポータル" }));

    await waitFor(() => expect(screen.getByText("Stripe 顧客が未作成です")).toBeTruthy());
  });
});

describe("SettingsPage — プラン変更", () => {
  it("現在のプランには active クラスを付け、ボタンを出さない", async () => {
    mockAuth(authSession());
    mockApis();

    const { container } = render(<SettingsPage />);
    await waitLoaded();

    await waitFor(() => expect(container.querySelectorAll(".plan-card")).toHaveLength(2));
    const freeCard = Array.from(container.querySelectorAll(".plan-card")).find((c) =>
      c.textContent?.includes("Free"),
    ) as HTMLElement;
    expect(freeCard.className).toContain("active");
    expect(freeCard.querySelector("button")).toBeNull();
  });

  it("Stripe 無効なら upgradePlan を呼びセッションを再取得する", async () => {
    const { refresh } = mockAuth(authSession());
    mockApis({ stripeEnabled: false });
    const upgrade = vi
      .spyOn(api, "upgradePlan")
      .mockResolvedValue({ tenant: { id: 1, name: "Example", slug: "example", plan: "pro" } });

    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "選択" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "選択" }));

    await waitFor(() => expect(upgrade).toHaveBeenCalledWith("pro"));
    await waitFor(() => expect(screen.getByText("pro プランに変更しました")).toBeTruthy());
    expect(refresh).toHaveBeenCalled();
  });

  it("Stripe 有効なら Checkout へ遷移し upgradePlan は呼ばない", async () => {
    const location = stubLocation();
    mockAuth(authSession());
    mockApis({ stripeEnabled: true });
    vi.spyOn(api, "createBillingCheckout").mockResolvedValue({
      checkout_url: "https://checkout.stripe.com/s/pro",
    });
    const upgrade = vi.spyOn(api, "upgradePlan");

    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Stripeで申込" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Stripeで申込" }));

    await waitFor(() => expect(location.href).toBe("https://checkout.stripe.com/s/pro"));
    expect(upgrade).not.toHaveBeenCalled();
  });

  it("プラン変更に失敗したらエラーを表示する", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "upgradePlan").mockRejectedValue(new Error("プラン変更に失敗しました"));

    render(<SettingsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "選択" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "選択" }));

    await waitFor(() => expect(screen.getByText("プラン変更に失敗しました")).toBeTruthy());
  });
});

describe("SettingsPage — OANDA 設定", () => {
  it("保存済みの口座 ID と環境を初期値にする", async () => {
    mockAuth(authSession());
    mockApis({
      oanda: {
        settings: { account_id: "101-001-999", environment: "live" },
        account_summary: { configured: false },
      } as Partial<OandaSettings>,
    });

    render(<SettingsPage />);
    await waitLoaded();

    await waitFor(() => expect((field("口座 ID") as HTMLInputElement).value).toBe("101-001-999"));
    expect((field("環境") as HTMLSelectElement).value).toBe("live");
  });

  it("接続済みなら残高サマリーを表示する", async () => {
    mockAuth(authSession());
    mockApis({
      oanda: {
        settings: {},
        account_summary: { configured: true, mode: "practice", balance: 123456, source: "oanda" },
      } as Partial<OandaSettings>,
    });

    render(<SettingsPage />);

    await waitFor(() =>
      expect(screen.getByText("接続状態: practice · $123,456 (oanda)")).toBeTruthy(),
    );
  });

  it("未接続ならメッセージを表示する", async () => {
    mockAuth(authSession());
    mockApis();

    render(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("接続状態: OANDA トークン未設定")).toBeTruthy());
  });

  it("トークン未入力なら api_token を送らない", async () => {
    mockAuth(authSession());
    mockApis();
    const update = vi.spyOn(api, "updateOandaSettings").mockResolvedValue({ settings: {} });

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "OANDA 設定を保存" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        account_id: "101-001-123",
        api_token: undefined,
        environment: "practice",
      }),
    );
  });

  it("入力した口座 ID・トークン・環境を保存し、入力欄をクリアする", async () => {
    mockAuth(authSession());
    mockApis();
    const update = vi.spyOn(api, "updateOandaSettings").mockResolvedValue({ settings: {} });

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.change(field("口座 ID"), { target: { value: "101-001-777" } });
    fireEvent.change(field("API トークン"), { target: { value: "secret-token" } });
    fireEvent.change(field("環境"), { target: { value: "live" } });
    fireEvent.click(screen.getByRole("button", { name: "OANDA 設定を保存" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        account_id: "101-001-777",
        api_token: "secret-token",
        environment: "live",
      }),
    );
    await waitFor(() => expect((field("API トークン") as HTMLInputElement).value).toBe(""));
    expect(screen.getByText("OANDA 設定を保存しました")).toBeTruthy();
  });

  it("保存後に設定を再取得してサマリーを更新する", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "updateOandaSettings").mockResolvedValue({ settings: {} });
    vi.mocked(api.getOandaSettings).mockResolvedValueOnce({
      settings: {},
      account_summary: { configured: false, message: "未設定" },
    } as OandaSettings).mockResolvedValueOnce({
      settings: {},
      account_summary: { configured: true, mode: "live", balance: 5000, source: "oanda" },
    } as OandaSettings);

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "OANDA 設定を保存" }));

    await waitFor(() =>
      expect(screen.getByText("接続状態: live · $5,000 (oanda)")).toBeTruthy(),
    );
  });

  it("保存に失敗したらエラーを表示する", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "updateOandaSettings").mockRejectedValue(new Error("トークンが不正です"));

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "OANDA 設定を保存" }));

    await waitFor(() => expect(screen.getByText("トークンが不正です")).toBeTruthy());
  });
});

describe("SettingsPage — API キー", () => {
  it("既存のキーを一覧表示する", async () => {
    mockAuth(authSession());
    mockApis();

    render(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("TradingView Webhook")).toBeTruthy());
    expect(screen.getByText("fx_abc")).toBeTruthy();
  });

  it("キー一覧の取得に失敗しても画面は描画される", async () => {
    mockAuth(authSession());
    mockApis();
    vi.mocked(api.listApiKeys).mockRejectedValue(new Error("403"));

    render(<SettingsPage />);

    await waitLoaded();
    expect(document.querySelectorAll(".data-table tbody tr")).toHaveLength(0);
  });

  it("入力した名前でキーを発行し、平文を一度だけ表示する", async () => {
    mockAuth(authSession());
    mockApis();
    const create = vi.spyOn(api, "createApiKey").mockResolvedValue({
      id: 2,
      name: "外部連携",
      api_key: "fx_live_secret",
      key_prefix: "fx_live",
    });

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.change(field("キー名"), { target: { value: "外部連携" } });
    fireEvent.click(screen.getByRole("button", { name: "キーを発行" }));

    await waitFor(() => expect(create).toHaveBeenCalledWith("外部連携"));
    await waitFor(() => expect(screen.getByText("fx_live_secret")).toBeTruthy());
    expect(screen.getByText(/再表示不可/)).toBeTruthy();
  });

  it("発行後にキー一覧を再取得する", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "createApiKey").mockResolvedValue({
      id: 2,
      name: "外部連携",
      api_key: "fx_live_secret",
      key_prefix: "fx_live",
    });

    render(<SettingsPage />);
    await waitLoaded();
    const before = vi.mocked(api.listApiKeys).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "キーを発行" }));

    await waitFor(() =>
      expect(vi.mocked(api.listApiKeys).mock.calls.length).toBe(before + 1),
    );
  });

  it("発行したキーをブラウザに保存できる", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "createApiKey").mockResolvedValue({
      id: 2,
      name: "k",
      api_key: "fx_live_secret",
      key_prefix: "fx_live",
    });
    const setApiKey = vi.spyOn(auth, "setApiKey").mockImplementation(() => {});

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "キーを発行" }));
    await waitFor(() => expect(screen.getByText("fx_live_secret")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "このブラウザに保存" }));

    expect(setApiKey).toHaveBeenCalledWith("fx_live_secret");
  });

  it("発行に失敗したらエラーを表示する", async () => {
    mockAuth(authSession());
    mockApis();
    vi.spyOn(api, "createApiKey").mockRejectedValue(new Error("キー上限に達しています"));

    render(<SettingsPage />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "キーを発行" }));

    await waitFor(() => expect(screen.getByText("キー上限に達しています")).toBeTruthy());
  });
});

describe("SettingsPage — Stripe 決済からの復帰", () => {
  it("?checkout=success ならメッセージを出しセッションを再取得する", async () => {
    stubLocation("http://localhost/settings?checkout=success");
    const { refresh } = mockAuth(authSession());
    mockApis();

    render(<SettingsPage />);

    await waitFor(() =>
      expect(screen.getByText("Stripe 決済が完了しました。プランを反映中...")).toBeTruthy(),
    );
    expect(refresh).toHaveBeenCalled();
  });

  it("クエリが無ければメッセージを出さない", async () => {
    stubLocation("http://localhost/settings");
    mockAuth(authSession());
    mockApis();

    render(<SettingsPage />);
    await waitLoaded();

    expect(screen.queryByText(/Stripe 決済が完了しました/)).toBeNull();
  });
});
