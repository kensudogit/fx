"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { SAAS_ENABLED } from "@/lib/auth";

const NAV_LINKS = [
  { href: "/", label: "テクニカル" },
  { href: "/fundamental", label: "ファンダ" },
  { href: "/analysis", label: "分析" },
  { href: "/ai", label: "AI" },
  { href: "/pro", label: "AI Pro" },
  { href: "/dashboard", label: "ダッシュボード" },
  { href: "/autotrade", label: "自動取引" },
  { href: "/pricing", label: "料金" },
] as const;

export function NavBar() {
  const { session, logout, loading } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    document.body.classList.toggle("nav-open", menuOpen);
    return () => document.body.classList.remove("nav-open");
  }, [menuOpen]);

  useEffect(() => {
    const close = () => setMenuOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, []);

  return (
    <header className="site-header">
      <div className="container header-inner">
        <a href="/" className="logo" onClick={() => setMenuOpen(false)}>
          FX Tool
        </a>
        <button
          type="button"
          className="nav-toggle"
          aria-label={menuOpen ? "メニューを閉じる" : "メニューを開く"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((o) => !o)}
        >
          <span className="nav-toggle-bar" />
          <span className="nav-toggle-bar" />
          <span className="nav-toggle-bar" />
        </button>
        <nav className={menuOpen ? "nav-open" : ""} aria-label="メインナビ">
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} onClick={() => setMenuOpen(false)}>
              {link.label}
            </a>
          ))}
          {SAAS_ENABLED && !loading && session && (
            <>
              <a href="/settings" onClick={() => setMenuOpen(false)}>
                設定
              </a>
              <span className="nav-user">{session.tenant.plan.toUpperCase()}</span>
              <button
                type="button"
                className="nav-logout"
                onClick={() => {
                  setMenuOpen(false);
                  logout();
                }}
              >
                ログアウト
              </button>
            </>
          )}
          {SAAS_ENABLED && !loading && !session && (
            <>
              <a href="/login" onClick={() => setMenuOpen(false)}>
                ログイン
              </a>
              <a href="/register" onClick={() => setMenuOpen(false)}>
                登録
              </a>
            </>
          )}
        </nav>
      </div>
      {menuOpen && (
        <button
          type="button"
          className="nav-backdrop"
          aria-label="メニューを閉じる"
          onClick={() => setMenuOpen(false)}
        />
      )}
    </header>
  );
}
