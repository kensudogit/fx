"use client";

import { useAuth } from "@/context/AuthContext";
import { SAAS_ENABLED } from "@/lib/auth";

export function NavBar() {
  const { session, logout, loading } = useAuth();

  return (
    <header>
      <div className="container">
        <a href="/" className="logo">
          FX Tool
        </a>
        <nav>
          <a href="/">テクニカル分析</a>
          <a href="/fundamental">ファンダメンタル分析</a>
          <a href="/analysis">マーケット分析</a>
          <a href="/ai">AI分析</a>
          <a href="/dashboard">統合ダッシュボード</a>
          <a href="/pricing">料金</a>
          {SAAS_ENABLED && !loading && session && (
            <>
              <a href="/settings">設定</a>
              <span className="nav-user">{session.tenant.plan.toUpperCase()}</span>
              <button type="button" className="nav-logout" onClick={logout}>
                ログアウト
              </button>
            </>
          )}
          {SAAS_ENABLED && !loading && !session && (
            <>
              <a href="/login">ログイン</a>
              <a href="/register">登録</a>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
