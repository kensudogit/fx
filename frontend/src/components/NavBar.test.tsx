/**
 * @file NavBar.test.tsx
 * @description `NavBar`（グローバルナビゲーション）のユニットテスト。
 *
 * 検証範囲:
 * - 8 つの固定ナビリンクとロゴの描画
 * - アクティブ判定（"/" は完全一致、他は前方一致）
 * - ハンバーガーメニューの開閉と aria 属性・body のクラス制御
 * - 各リンク／背景クリックでメニューが閉じること
 * - hashchange でメニューが閉じること
 * - 認証状態による表示切り替え（ログイン中 / 未ログイン / 読み込み中）
 * - ログアウトボタンの動作
 * - アンマウント時に body のクラスを除去すること
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NavBar } from "./NavBar";
import * as authContext from "@/context/AuthContext";
import { authSession } from "@/test/fixtures";

/** usePathname を差し替えて任意のパスを再現する */
const pathname = { current: "/" };
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

/** useAuth の戻り値を差し替える */
function mockAuth(over: Partial<ReturnType<typeof authContext.useAuth>> = {}) {
  const logout = vi.fn();
  vi.spyOn(authContext, "useAuth").mockReturnValue({
    saasEnabled: true,
    session: null,
    loading: false,
    refresh: vi.fn(),
    logout,
    ...over,
  });
  return { logout };
}

/** ナビゲーション内の指定テキストのリンクを取得する */
function navLink(label: string): HTMLAnchorElement {
  return screen.getByRole("link", { name: label }) as HTMLAnchorElement;
}

describe("NavBar — 基本の描画", () => {
  it("ロゴと 8 つのナビリンクを表示する", () => {
    pathname.current = "/";
    mockAuth();

    render(<NavBar />);

    expect(navLink("FX Tool").getAttribute("href")).toBe("/");
    for (const [label, href] of [
      ["テクニカル", "/"],
      ["ファンダ", "/fundamental"],
      ["分析", "/analysis"],
      ["AI", "/ai"],
      ["AI Pro", "/pro"],
      ["ダッシュボード", "/dashboard"],
      ["自動取引", "/autotrade"],
      ["料金", "/pricing"],
    ] as const) {
      expect(navLink(label).getAttribute("href")).toBe(href);
    }
  });

  it("メインナビに aria-label を設定する", () => {
    pathname.current = "/";
    mockAuth();
    render(<NavBar />);
    expect(screen.getByRole("navigation", { name: "メインナビ" })).toBeTruthy();
  });
});

describe("NavBar — アクティブ判定", () => {
  it('"/" ではテクニカルのみをアクティブにする', () => {
    pathname.current = "/";
    mockAuth();

    render(<NavBar />);

    expect(navLink("テクニカル").className).toBe("active");
    expect(navLink("分析").className).toBe("");
  });

  it("他ページでは前方一致でアクティブにし、トップは外す", () => {
    pathname.current = "/analysis";
    mockAuth();

    render(<NavBar />);

    expect(navLink("分析").className).toBe("active");
    expect(navLink("テクニカル").className).toBe("");
  });

  it("サブパスでも親リンクをアクティブにする", () => {
    pathname.current = "/autotrade/logs";
    mockAuth();

    render(<NavBar />);

    expect(navLink("自動取引").className).toBe("active");
  });
});

describe("NavBar — モバイルメニュー", () => {
  it("初期状態は閉じていて aria-expanded=false", () => {
    pathname.current = "/";
    mockAuth();

    render(<NavBar />);

    const toggle = screen.getByRole("button", { name: "メニューを開く" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("トグルで開閉し、body に nav-open クラスを付け外しする", () => {
    pathname.current = "/";
    mockAuth();

    render(<NavBar />);

    const toggle = screen.getByRole("button", { name: "メニューを開く" });
    fireEvent.click(toggle);
    expect(document.body.classList.contains("nav-open")).toBe(true);
    // 開いている間はトグル自身とバックドロップの 2 つが「メニューを閉じる」になる
    expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(2);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(toggle);
    expect(document.body.classList.contains("nav-open")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("開いているときは背景（バックドロップ）を表示する", () => {
    pathname.current = "/";
    mockAuth();
    const { container } = render(<NavBar />);

    expect(container.querySelector(".nav-backdrop")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    expect(container.querySelector(".nav-backdrop")).toBeTruthy();
  });

  it("背景クリックでメニューを閉じる", () => {
    pathname.current = "/";
    mockAuth();
    const { container } = render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    fireEvent.click(container.querySelector(".nav-backdrop") as HTMLElement);

    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("ナビリンクをクリックするとメニューを閉じる", () => {
    pathname.current = "/";
    mockAuth();
    render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    fireEvent.click(navLink("分析"));

    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("ロゴクリックでもメニューを閉じる", () => {
    pathname.current = "/";
    mockAuth();
    render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    fireEvent.click(navLink("FX Tool"));

    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("hashchange イベントでメニューを閉じる", () => {
    pathname.current = "/";
    mockAuth();
    render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    fireEvent(window, new Event("hashchange"));

    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("アンマウント時に body の nav-open を除去する", () => {
    pathname.current = "/";
    mockAuth();
    const { unmount } = render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    unmount();

    expect(document.body.classList.contains("nav-open")).toBe(false);
  });
});

describe("NavBar — 認証状態による切り替え", () => {
  it("ログイン中は設定リンク・プランバッジ・ログアウトを表示する", () => {
    pathname.current = "/";
    mockAuth({ session: authSession({ tenant: { id: 1, name: "X", slug: "x", plan: "pro" } }) });

    render(<NavBar />);

    expect(navLink("設定").getAttribute("href")).toBe("/settings");
    expect(screen.getByText("PRO")).toBeTruthy();
    expect(screen.getByRole("button", { name: "ログアウト" })).toBeTruthy();
    expect(screen.queryByText("ログイン")).toBeNull();
  });

  it("未ログイン時はログイン・無料登録リンクを表示する", () => {
    pathname.current = "/";
    mockAuth({ session: null });

    render(<NavBar />);

    expect(navLink("ログイン").getAttribute("href")).toBe("/login");
    expect(navLink("無料登録").getAttribute("href")).toBe("/register");
    expect(screen.queryByText("設定")).toBeNull();
  });

  it("読み込み中はどちらの認証 UI も表示しない", () => {
    pathname.current = "/";
    mockAuth({ loading: true });

    render(<NavBar />);

    expect(screen.queryByText("ログイン")).toBeNull();
    expect(screen.queryByText("設定")).toBeNull();
  });

  it("ログアウトボタンでメニューを閉じて logout を呼ぶ", () => {
    pathname.current = "/";
    const { logout } = mockAuth({ session: authSession() });
    render(<NavBar />);
    fireEvent.click(screen.getByRole("button", { name: "メニューを開く" }));

    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("/settings では設定リンクをアクティブにする", () => {
    pathname.current = "/settings";
    mockAuth({ session: authSession() });

    render(<NavBar />);

    expect(navLink("設定").className).toBe("active");
  });
});
