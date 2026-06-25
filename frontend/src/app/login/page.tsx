"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { authLogin } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await authLogin(email, password);
      setAccessToken(res.access_token);
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ログインに失敗しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card auth-card">
        <h1>ログイン</h1>
        <p className="hint">FX Tool SaaS ワークスペースにサインイン</p>
        <form onSubmit={submit} className="auth-form">
          <label>
            メールアドレス
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
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
          {error && <p className="error-text">{error}</p>}
          <button type="submit" className="btn" disabled={loading}>
            {loading ? "ログイン中..." : "ログイン"}
          </button>
        </form>
        <p className="hint">
          アカウント未作成の方は <a href="/register">新規登録</a>
        </p>
      </div>
    </div>
  );
}
