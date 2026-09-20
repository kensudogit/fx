/**
 * @file register/page.test.tsx
 * @description `RegisterPage`（/register）のユニットテスト。
 *
 * 検証範囲:
 * - フォームの構造（組織名・メール・パスワードの型・必須・最小長）
 * - 送信時の authRegister 呼び出し（引数の順序に注意）
 * - 成功時の自動ログイン（トークン保存）とトップページ遷移
 * - 失敗時のエラー表示（Error 以外は汎用文言）
 * - 送信中のボタン非活性化とラベル変更
 * - ログインページへのリンク
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RegisterPage from "./page";
import * as api from "@/lib/api";
import * as auth from "@/lib/auth";

/** useRouter を差し替える */
const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

/** 登録成功時のレスポンス */
function registerResult(token = "jwt-new") {
  return {
    access_token: token,
    user: { id: 9, email: "new@example.com", role: "admin", tenant_id: 9 },
    tenant: { id: 9, name: "新規組織", slug: "new-org", plan: "free" },
  };
}

/** フォームに入力して送信する */
function submit(org = "新規組織", email = "new@example.com", password = "password1") {
  fireEvent.change(screen.getByLabelText("組織名"), { target: { value: org } });
  fireEvent.change(screen.getByLabelText("メールアドレス"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("パスワード（8文字以上）"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "アカウント作成" }));
}

describe("RegisterPage — フォームの構造", () => {
  it("見出しと 3 つの入力欄を表示する", () => {
    render(<RegisterPage />);

    expect(screen.getByRole("heading", { name: "新規登録" })).toBeTruthy();
    expect(screen.getByLabelText("組織名")).toBeTruthy();
    expect(screen.getByLabelText("メールアドレス")).toBeTruthy();
    expect(screen.getByLabelText("パスワード（8文字以上）")).toBeTruthy();
  });

  it("Free プランから開始する旨を案内する", () => {
    render(<RegisterPage />);
    expect(screen.getByText(/Free プランから開始/)).toBeTruthy();
  });

  it("組織名は必須のテキスト入力", () => {
    render(<RegisterPage />);
    const el = screen.getByLabelText("組織名") as HTMLInputElement;

    expect(el.required).toBe(true);
    expect(el.type).toBe("text");
  });

  it("パスワードは type=password・8 文字以上", () => {
    render(<RegisterPage />);
    const el = screen.getByLabelText("パスワード（8文字以上）") as HTMLInputElement;

    expect(el.type).toBe("password");
    expect(el.minLength).toBe(8);
  });

  it("ログインページへのリンクを表示する", () => {
    render(<RegisterPage />);
    expect((screen.getByText("ログイン") as HTMLAnchorElement).getAttribute("href")).toBe("/login");
  });
});

describe("RegisterPage — 送信", () => {
  it("メール・パスワード・組織名の順で authRegister を呼ぶ", async () => {
    const reg = vi.spyOn(api, "authRegister").mockResolvedValue(registerResult());
    vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});

    render(<RegisterPage />);
    submit("Example 社", "trader@example.com", "secret123");

    await waitFor(() =>
      expect(reg).toHaveBeenCalledWith("trader@example.com", "secret123", "Example 社"),
    );
  });

  it("成功したら自動ログインしてトップページへ遷移する", async () => {
    vi.spyOn(api, "authRegister").mockResolvedValue(registerResult("jwt-new"));
    const setToken = vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});

    render(<RegisterPage />);
    submit();

    await waitFor(() => expect(setToken).toHaveBeenCalledWith("jwt-new"));
    expect(router.push).toHaveBeenCalledWith("/");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("送信中はボタンを非活性化しラベルを変える", () => {
    vi.spyOn(api, "authRegister").mockReturnValue(new Promise(() => {}));

    render(<RegisterPage />);
    submit();

    expect((screen.getByRole("button", { name: "登録中..." }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});

describe("RegisterPage — エラー", () => {
  it("API のエラーメッセージを表示する", async () => {
    vi.spyOn(api, "authRegister").mockRejectedValue(
      new Error("このメールアドレスは登録済みです"),
    );

    render(<RegisterPage />);
    submit();

    await waitFor(() => expect(screen.getByText("このメールアドレスは登録済みです")).toBeTruthy());
  });

  it("Error でない例外は汎用メッセージにする", async () => {
    vi.spyOn(api, "authRegister").mockRejectedValue({ status: 500 });

    render(<RegisterPage />);
    submit();

    await waitFor(() => expect(screen.getByText("登録に失敗しました")).toBeTruthy());
  });

  it("失敗時はトークンを保存せず遷移もしない", async () => {
    vi.spyOn(api, "authRegister").mockRejectedValue(new Error("失敗"));
    const setToken = vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});
    router.push.mockClear();

    render(<RegisterPage />);
    submit();

    await waitFor(() => expect(screen.getByText("失敗")).toBeTruthy());
    expect(setToken).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });
});
