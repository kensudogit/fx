/**
 * @file login/page.tsx
 * @description ログインページ
 *
 * URL: /login
 *
 * 主要機能:
 * - メールアドレス・パスワードによる認証フォーム
 * - POST /api/auth/login への認証リクエスト送信
 * - 認証成功時にアクセストークンをローカルストレージへ保存
 * - ログイン成功後にトップページへリダイレクト
 * - バリデーションエラーおよびサーバーエラーのインライン表示
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { authLogin } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

/**
 * LoginPage コンポーネント
 *
 * ユーザー認証フォームを提供するページコンポーネント。
 * フォーム送信後に authLogin API を呼び出し、成功時はトークンを保存して
 * トップページへ遷移する。失敗時はエラーメッセージをフォーム内に表示する。
 */
export default function LoginPage() {
  // Next.js のルーターインスタンス（ログイン後のリダイレクトに使用）
  const router = useRouter();

  // メールアドレス入力値のステート
  const [email, setEmail] = useState("");

  // パスワード入力値のステート
  const [password, setPassword] = useState("");

  // ログイン失敗時に表示するエラーメッセージ（null = エラーなし）
  const [error, setError] = useState<string | null>(null);

  // API リクエスト送信中かどうかを示すフラグ（二重送信防止・ボタン非活性化に使用）
  const [loading, setLoading] = useState(false);

  /**
   * フォーム送信ハンドラー
   *
   * ブラウザデフォルトのフォーム送信を preventDefault で防ぎ、
   * authLogin API（POST /api/auth/login）を呼び出す。
   * 認証成功時: アクセストークンを保存してトップページへ遷移
   * 認証失敗時: エラーメッセージをステートに格納してフォームに表示
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
      // POST /api/auth/login にメール・パスワードを送信してトークンを取得
      const res = await authLogin(email, password);
      // 取得したアクセストークンをローカルストレージに保存
      setAccessToken(res.access_token);
      // ログイン成功後にトップページへ遷移
      router.push("/");
      // サーバーコンポーネントのキャッシュを最新化
      router.refresh();
    } catch (err) {
      // Error インスタンスからメッセージを取得し、それ以外は汎用メッセージを使用
      setError(err instanceof Error ? err.message : "ログインに失敗しました");
    } finally {
      // 成功・失敗いずれの場合もローディング状態を解除
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>ログイン</h1>
        <p className="hint">FX Tool SaaS ワークスペースにサインイン</p>
        {/* 認証フォーム: submit ハンドラーに送信イベントを委譲 */}
        <form onSubmit={submit} className="auth-form">
          {/* メールアドレス入力フィールド（HTML5 email バリデーション付き・必須） */}
          <label>
            メールアドレス
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {/* パスワード入力フィールド（最低 8 文字・必須） */}
          <label>
            パスワード
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {/* エラーメッセージ: ログイン失敗時のみ表示 */}
          {error && <p className="error-text">{error}</p>}
          {/* 送信ボタン: API 通信中は非活性化してテキストを変更 */}
          <button type="submit" className="btn" disabled={loading}>
            {loading ? "ログイン中..." : "ログイン"}
          </button>
        </form>
        {/* 新規登録ページへのリンク */}
        <p className="hint">
          アカウント未作成の方は <a href="/register">新規登録</a>
        </p>
      </div>
    </div>
  );
}
