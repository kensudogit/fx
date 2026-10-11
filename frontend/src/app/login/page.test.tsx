/**
 * @file login/page.test.tsx
 * @description `LoginPage`（/login）のユニットテスト。
 *
 * 検証範囲:
 * - フォームの構造（メール・パスワードの型・必須・最小長）
 * - 送信時の authLogin 呼び出しとトークン保存
 * - 成功時のトップページ遷移とキャッシュ更新
 * - 失敗時のエラー表示（Error 以外は汎用文言）
 * - 送信中のボタン非活性化とラベル変更、再送信時のエラークリア
 * - 新規登録ページへのリンク
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LoginPage from "./page";
import * as api from "@/lib/api";
import * as auth from "@/lib/auth";

/** useRouter を差し替える */
const router = { push: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

/** 認証成功時のレスポンス */
function loginResult(token = "jwt-abc") {
  return {
    access_token: token,
    user: { id: 1, email: "a@example.com", role: "admin", tenant_id: 1 },
    tenant: { id: 1, name: "Example", slug: "example", plan: "free" },
  };
}

/** フォームに値を入力して送信する */
function submit(email = "a@example.com", password = "password1") {
  fireEvent.change(screen.getByLabelText("メールアドレス"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("パスワード"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "ログイン" }));
}

describe("LoginPage — フォームの構造", () => {
  it("見出しと入力欄を表示する", () => {
    render(<LoginPage />);

    expect(screen.getByRole("heading", { name: "ログイン" })).toBeTruthy();
    expect(screen.getByLabelText("メールアドレス")).toBeTruthy();
    expect(screen.getByLabelText("パスワード")).toBeTruthy();
  });

  it("メールは type=email かつ必須", () => {
    render(<LoginPage />);
    const el = screen.getByLabelText("メールアドレス") as HTMLInputElement;

    expect(el.type).toBe("email");
    expect(el.required).toBe(true);
  });

  it("パスワードは type=password・必須・8 文字以上", () => {
    render(<LoginPage />);
    const el = screen.getByLabelText("パスワード") as HTMLInputElement;

    expect(el.type).toBe("password");
    expect(el.required).toBe(true);
    expect(el.minLength).toBe(8);
  });

  it("新規登録ページへのリンクを表示する", () => {
    render(<LoginPage />);
    expect((screen.getByText("新規登録") as HTMLAnchorElement).getAttribute("href")).toBe(
      "/register",
    );
  });
});

describe("LoginPage — 送信", () => {
  it("入力値で authLogin を呼ぶ", async () => {
    const login = vi.spyOn(api, "authLogin").mockResolvedValue(loginResult());
    vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});

    render(<LoginPage />);
    submit("trader@example.com", "secret123");

    await waitFor(() => expect(login).toHaveBeenCalledWith("trader@example.com", "secret123"));
  });

  it("成功したらトークンを保存しトップページへ遷移する", async () => {
    vi.spyOn(api, "authLogin").mockResolvedValue(loginResult("jwt-xyz"));
    const setToken = vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});

    render(<LoginPage />);
    submit();

    await waitFor(() => expect(setToken).toHaveBeenCalledWith("jwt-xyz"));
    expect(router.push).toHaveBeenCalledWith("/");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("送信中はボタンを非活性化しラベルを変える", async () => {
    vi.spyOn(api, "authLogin").mockReturnValue(new Promise(() => {}));

    render(<LoginPage />);
    submit();

    const btn = screen.getByRole("button", { name: "ログイン中..." }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

describe("LoginPage — エラー", () => {
  it("API のエラーメッセージを表示する", async () => {
    vi.spyOn(api, "authLogin").mockRejectedValue(new Error("メールまたはパスワードが違います"));

    render(<LoginPage />);
    submit();

    await waitFor(() => expect(screen.getByText("メールまたはパスワードが違います")).toBeTruthy());
  });

  it("Error でない例外は汎用メッセージにする", async () => {
    vi.spyOn(api, "authLogin").mockRejectedValue("unknown");

    render(<LoginPage />);
    submit();

    await waitFor(() => expect(screen.getByText("ログインに失敗しました")).toBeTruthy());
  });

  it("エラー後もボタンは再度押せる状態に戻る", async () => {
    vi.spyOn(api, "authLogin").mockRejectedValue(new Error("失敗"));

    render(<LoginPage />);
    submit();

    await waitFor(() =>
      expect((screen.getByRole("button", { name: "ログイン" }) as HTMLButtonElement).disabled).toBe(
        false,
      ),
    );
  });

  it("再送信時に前回のエラーを消す", async () => {
    const login = vi
      .spyOn(api, "authLogin")
      .mockRejectedValueOnce(new Error("失敗しました"))
      .mockResolvedValueOnce(loginResult());
    vi.spyOn(auth, "setAccessToken").mockImplementation(() => {});

    render(<LoginPage />);
    submit();
    await waitFor(() => expect(screen.getByText("失敗しました")).toBeTruthy());

    submit();

    await waitFor(() => expect(login).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("失敗しました")).toBeNull());
  });
});
