/**
 * @file register/page.tsx
 * @description 新規ユーザー登録ページ
 *
 * URL: /register
 *
 * 主要機能:
 * - 組織名（テナント名）・メールアドレス・パスワードの入力フォーム
 * - POST /api/auth/register への新規登録リクエスト送信
 * - 登録成功時に自動ログイン（アクセストークン保存）してトップページへ遷移
 * - 登録時に Free プランのテナント（組織）が自動生成される
 * - バリデーションエラーおよびサーバーエラーのインライン表示
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { authRegister } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

/**
 * RegisterPage コンポーネント
 *
 * 新規ユーザー登録フォームを提供するページコンポーネント。
 * 組織名・メール・パスワードを入力後、authRegister API を呼び出して
 * テナント（組織）を作成し、Free プランで利用を開始する。
 * 登録成功時は取得したアクセストークンを保存してトップページへ遷移する。
 */
export default function RegisterPage() {
  // Next.js のルーターインスタンス（登録後のリダイレクトに使用）
  const router = useRouter();

  // 組織名（テナント名）入力値のステート
  const [orgName, setOrgName] = useState("");

  // メールアドレス入力値のステート
  const [email, setEmail] = useState("");

  // パスワード入力値のステート
  const [password, setPassword] = useState("");

  // 登録失敗時に表示するエラーメッセージ（null = エラーなし）
  const [error, setError] = useState<string | null>(null);

  // API リクエスト送信中かどうかを示すフラグ（二重送信防止・ボタン非活性化に使用）
  const [loading, setLoading] = useState(false);

  /**
   * フォーム送信ハンドラー
   *
   * ブラウザデフォルトのフォーム送信を preventDefault で防ぎ、
   * authRegister API（POST /api/auth/register）を呼び出す。
   * 登録成功時: 自動ログイン用のアクセストークンを保存してトップページへ遷移
   * 登録失敗時: エラーメッセージをステートに格納してフォームに表示
   *
   * @param e - フォーム送信イベント
   */
  const submit = async (e: React.FormEvent) => {
    // ブラウザのデフォルトフォーム送信（ページリロード）を防止
    e.preventDefault();
    setLoading(true);
    // 前回のエラーメッセージをリセット
    setError(null);
    try {
      // POST /api/auth/register にメール・パスワード・組織名を送信してトークンを取得
      // テナント（組織）が新規作成され Free プランが割り当てられる
      const res = await authRegister(email, password, orgName);
      // 取得したアクセストークンをローカルストレージに保存（自動ログイン）
      setAccessToken(res.access_token);
      // 登録成功後にトップページへ遷移
      router.push("/");
      // サーバーコンポーネントのキャッシュを最新化
      router.refresh();
    } catch (err) {
      // Error インスタンスからメッセージを取得し、それ以外は汎用メッセージを使用
      setError(err instanceof Error ? err.message : "登録に失敗しました");
    } finally {
      // 成功・失敗いずれの場合もローディング状態を解除
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>新規登録</h1>
        <p className="hint">組織（テナント）を作成して Free プランから開始</p>
        {/* 新規登録フォーム: submit ハンドラーに送信イベントを委譲 */}
        <form onSubmit={submit} className="auth-form">
          {/* 組織名入力フィールド（必須・マルチテナント識別子として使用される） */}
          <label>
            組織名
            <input required value={orgName} onChange={(e) => setOrgName(e.target.value)} />
          </label>
          {/* メールアドレス入力フィールド（HTML5 email バリデーション付き・必須） */}
          <label>
            メールアドレス
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {/* パスワード入力フィールド（最低 8 文字・必須） */}
          <label>
            パスワード（8文字以上）
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {/* エラーメッセージ: 登録失敗時のみ表示 */}
          {error && <p className="error-text">{error}</p>}
          {/* 送信ボタン: API 通信中は非活性化してテキストを変更 */}
          <button type="submit" className="btn" disabled={loading}>
            {loading ? "登録中..." : "アカウント作成"}
          </button>
        </form>
        {/* 既存アカウント保持者向けのログインページリンク */}
        <p className="hint">
          既にアカウントをお持ちの方は <a href="/login">ログイン</a>
        </p>
      </div>
    </div>
  );
}
