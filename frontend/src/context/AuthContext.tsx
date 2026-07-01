/**
 * @file AuthContext.tsx
 * @description 認証状態をアプリ全体に提供する React Context。
 *
 * アプリ起動時に JWT トークンの有無を確認し、バックエンドの `/api/auth/me` で
 * セッション情報を取得してコンテキストに格納する。
 * SaaS モード（SAAS_ENABLED=true）が無効な場合は認証チェックをスキップする。
 *
 * 提供する値:
 * - `saasEnabled` — SaaS 認証機能が有効かどうか
 * - `session` — 現在のユーザー・テナント・利用状況情報（未ログイン時は `null`）
 * - `loading` — セッション取得中かどうか（初回レンダリング時のフラッシュ防止用）
 * - `refresh` — セッション情報を再取得する非同期関数（ログイン後に呼び出す）
 * - `logout` — 認証情報をクリアしてログインページへリダイレクトする関数
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { authMe, type AuthSession } from "@/lib/api";
import { clearAuth, getAccessToken, SAAS_ENABLED } from "@/lib/auth";

/**
 * AuthContext が提供する値の型定義。
 */
interface AuthContextValue {
  /** SaaS モードが有効かどうか（環境変数 NEXT_PUBLIC_SAAS_ENABLED で制御）*/
  saasEnabled: boolean;
  /** 現在のログインセッション情報。未認証または SaaS 無効時は `null` */
  session: AuthSession | null;
  /** セッション取得中かどうか。`true` の間はローディングスピナーを表示する */
  loading: boolean;
  /**
   * バックエンドからセッション情報を再取得する。
   * ログイン成功後や設定変更後に呼び出してセッションを最新化する。
   */
  refresh: () => Promise<void>;
  /**
   * ログアウトを実行する。
   * localStorage と Cookie から認証情報を削除し、`/login` へリダイレクトする。
   */
  logout: () => void;
}

/**
 * AuthContext のデフォルト値（Provider の外側で useAuth を呼んだ場合に使用される）。
 * 実際のアプリでは AuthProvider が常に最上位に配置されるため、
 * このデフォルト値が使われることは通常ない。
 */
const AuthContext = createContext<AuthContextValue>({
  saasEnabled: SAAS_ENABLED,
  session: null,
  loading: true,
  refresh: async () => {},
  logout: () => {},
});

/**
 * 認証状態を子コンポーネントに提供する Provider コンポーネント。
 *
 * マウント時に自動で `refresh()` を実行してセッション情報を取得する。
 * `_app.tsx` または `layout.tsx` の最上位に配置すること。
 *
 * @param children - Provider でラップする子コンポーネント
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  /** 現在のセッション情報。未取得または未認証時は `null` */
  const [session, setSession] = useState<AuthSession | null>(null);

  /**
   * ローディング状態。
   * SaaS モードが有効な場合のみ初期値を `true` にして、
   * セッション取得完了まで子コンポーネントのレンダリングをブロックできるようにする。
   * SaaS 無効の場合は最初から `false`（常に認証不要）。
   */
  const [loading, setLoading] = useState(SAAS_ENABLED);

  /**
   * セッション情報を再取得する関数。
   *
   * 処理フロー:
   * 1. SaaS 無効またはトークンが存在しない場合 → セッションを `null` にして終了
   * 2. `/api/auth/me` を呼び出してセッション情報を取得
   * 3. 成功時 → `session` を更新
   * 4. 失敗時（401 等）→ 認証情報をクリアして `session` を `null` に設定
   * 5. 常に `loading` を `false` にする
   *
   * `useCallback` でメモ化し、不要な再生成を防ぐ（依存なし）。
   */
  const refresh = useCallback(async () => {
    // SaaS モードが無効、またはトークンが存在しない場合は認証チェック不要
    if (!SAAS_ENABLED || !getAccessToken()) {
      setSession(null);
      setLoading(false);
      return;
    }
    try {
      // JWT トークンを使って現在のセッション情報をバックエンドから取得する
      setSession(await authMe());
    } catch {
      // トークンが無効・期限切れの場合は認証情報を削除してセッションをクリア
      clearAuth();
      setSession(null);
    } finally {
      // 成功・失敗いずれの場合もローディングを終了する
      setLoading(false);
    }
  }, []);

  /**
   * コンポーネントのマウント時にセッション情報を取得する。
   * `refresh` は `useCallback` でメモ化されているため、このエフェクトは一度だけ実行される。
   */
  useEffect(() => {
    refresh();
  }, [refresh]);

  /**
   * ログアウト処理。
   *
   * 1. localStorage・Cookie から認証情報をすべて削除する
   * 2. React ステートの `session` を `null` に設定する
   * 3. ログインページ（`/login`）へハードナビゲートする
   */
  const logout = () => {
    clearAuth();
    setSession(null);
    window.location.href = "/login";
  };

  return (
    // コンテキスト値を子コンポーネントツリー全体に提供する
    <AuthContext.Provider value={{ saasEnabled: SAAS_ENABLED, session, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * AuthContext の値を取得するカスタムフック。
 *
 * このフックは必ず {@link AuthProvider} の子コンポーネント内で使用すること。
 *
 * @returns {@link AuthContextValue} — 認証状態・セッション情報・操作関数
 *
 * @example
 * ```tsx
 * const { session, loading, logout } = useAuth();
 * if (loading) return <Spinner />;
 * if (!session) return <Redirect to="/login" />;
 * ```
 */
export function useAuth() {
  return useContext(AuthContext);
}
