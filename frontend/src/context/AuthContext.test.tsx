/**
 * @file AuthContext.test.tsx
 * @description `src/context/AuthContext.tsx`（認証コンテキスト）のユニットテスト。
 *
 * 検証範囲:
 * - マウント時の自動 refresh（トークンあり / なし）
 * - `/api/auth/me` 失敗時に認証情報をクリアしてセッションを null にすること
 * - loading の初期値と収束
 * - logout の副作用（認証情報削除・セッション破棄・/login への遷移）
 * - refresh を手動で呼んだときのセッション更新
 * - Provider 外で useAuth を使った場合のデフォルト値
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext";
import { setAccessToken } from "@/lib/auth";
import * as api from "@/lib/api";
import * as fixtures from "@/test/fixtures";
import { stubLocation } from "@/test/utils";

/** コンテキストの内容を DOM に書き出す検査用コンポーネント */
function Probe() {
  const { session, loading, saasEnabled, logout, refresh } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="saas">{String(saasEnabled)}</span>
      <span data-testid="email">{session?.user.email ?? "none"}</span>
      <button type="button" onClick={logout}>
        ログアウト
      </button>
      <button type="button" onClick={() => void refresh()}>
        再取得
      </button>
    </div>
  );
}

/** AuthProvider でラップして Probe を描画する */
function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe("AuthContext — 初期ロード", () => {
  it("トークンが無い場合は API を呼ばずセッションを null にする", async () => {
    const authMe = vi.spyOn(api, "authMe");
    renderProvider();

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
    expect(authMe).not.toHaveBeenCalled();
    expect(screen.getByTestId("email").textContent).toBe("none");
  });

  it("トークンがある場合は /api/auth/me でセッションを取得する", async () => {
    setAccessToken("jwt-abc");
    vi.spyOn(api, "authMe").mockResolvedValue(fixtures.authSession());

    renderProvider();

    await waitFor(() =>
      expect(screen.getByTestId("email").textContent).toBe("trader@example.com"),
    );
    expect(screen.getByTestId("loading").textContent).toBe("false");
  });

  it("SaaS モードが有効なので saasEnabled は true", async () => {
    renderProvider();
    await waitFor(() => expect(screen.getByTestId("saas").textContent).toBe("true"));
  });

  it("取得に失敗した場合は認証情報をクリアしてセッションを null にする", async () => {
    setAccessToken("jwt-expired");
    vi.spyOn(api, "authMe").mockRejectedValue(new Error("401 Unauthorized"));

    renderProvider();

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
    expect(screen.getByTestId("email").textContent).toBe("none");
    expect(localStorage.getItem("fx_access_token")).toBeNull();
  });

  it("取得が完了するまで loading が true のまま", async () => {
    setAccessToken("jwt-abc");
    let resolve!: (s: api.AuthSession) => void;
    vi.spyOn(api, "authMe").mockReturnValue(
      new Promise<api.AuthSession>((r) => {
        resolve = r;
      }),
    );

    renderProvider();
    expect(screen.getByTestId("loading").textContent).toBe("true");

    await act(async () => {
      resolve(fixtures.authSession());
    });

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
  });
});

describe("AuthContext — refresh", () => {
  it("呼び出すたびに最新のセッションを取り込む", async () => {
    setAccessToken("jwt-abc");
    const authMe = vi
      .spyOn(api, "authMe")
      .mockResolvedValueOnce(fixtures.authSession())
      .mockResolvedValueOnce(
        fixtures.authSession({
          user: { id: 1, email: "upgraded@example.com", role: "admin", tenant_id: 1 },
        }),
      );

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("email").textContent).toBe("trader@example.com"),
    );

    await act(async () => {
      screen.getByText("再取得").click();
    });

    await waitFor(() =>
      expect(screen.getByTestId("email").textContent).toBe("upgraded@example.com"),
    );
    expect(authMe).toHaveBeenCalledTimes(2);
  });
});

describe("AuthContext — logout", () => {
  it("認証情報を削除しセッションを破棄して /login へ遷移する", async () => {
    const location = stubLocation();
    setAccessToken("jwt-abc");
    vi.spyOn(api, "authMe").mockResolvedValue(fixtures.authSession());

    renderProvider();
    await waitFor(() =>
      expect(screen.getByTestId("email").textContent).toBe("trader@example.com"),
    );

    await act(async () => {
      screen.getByText("ログアウト").click();
    });

    expect(localStorage.getItem("fx_access_token")).toBeNull();
    expect(screen.getByTestId("email").textContent).toBe("none");
    expect(location.href).toBe("/login");
  });
});

describe("AuthContext — Provider 外での利用", () => {
  it("デフォルト値（session=null / loading=true）を返す", () => {
    render(<Probe />);

    expect(screen.getByTestId("email").textContent).toBe("none");
    expect(screen.getByTestId("loading").textContent).toBe("true");
  });

  it("デフォルトの refresh / logout は呼んでも例外にならない", () => {
    render(<Probe />);
    expect(() => screen.getByText("ログアウト").click()).not.toThrow();
    expect(() => screen.getByText("再取得").click()).not.toThrow();
  });
});
