/**
 * Next.js ページ — page
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { authRegister } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await authRegister(email, password, orgName);
      setAccessToken(res.access_token);
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登録に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>新規登録</h1>
        <p className="hint">組織（テナント）を作成して Free プランから開始</p>
        <form onSubmit={submit} className="auth-form">
          <label>
            組織名
            <input required value={orgName} onChange={(e) => setOrgName(e.target.value)} />
          </label>
          <label>
            メールアドレス
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
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
          {error && <p className="error-text">{error}</p>}
          <button type="submit" className="btn" disabled={loading}>
            {loading ? "登録中..." : "アカウント作成"}
          </button>
        </form>
        <p className="hint">
          既にアカウントをお持ちの方は <a href="/login">ログイン</a>
        </p>
      </div>
    </div>
  );
}
