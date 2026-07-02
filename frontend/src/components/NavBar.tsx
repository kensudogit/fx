/**
 * @file NavBar.tsx
 * @description サイト共通ナビゲーションバー
 *
 * 全ページの最上部に固定表示されるヘッダーコンポーネント。
 * 主要ページへのリンク一覧・ハンバーガーメニュー（モバイル）・
 * 認証状態に応じたログイン/ログアウトボタン・プラン表示を提供する。
 *
 * 認証機能（SaaS モード）が有効な場合は `SAAS_ENABLED` フラグで制御され、
 * ログイン中はプラン名・設定リンク・ログアウトボタンを、
 * 未ログイン時はログイン・登録リンクを表示する。
 */

"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { SAAS_ENABLED } from "@/lib/auth";

/**
 * ナビゲーションに表示するリンク一覧の定義。
 * 順序がそのままナビバーの表示順になる。
 */
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

/**
 * NavBar
 *
 * サイト全体のヘッダーナビゲーションコンポーネント。
 *
 * ### 認証状態の連動
 * - `SAAS_ENABLED` が false の場合、認証関連 UI は一切表示しない
 * - ロード中（`loading === true`）は認証 UI を非表示にしてレイアウトのずれを防ぐ
 * - ログイン中: プラン名（例: "PRO"）・設定リンク・ログアウトボタンを表示
 * - 未ログイン: ログイン・登録リンクを表示
 *
 * ### モバイル対応
 * - ハンバーガーボタンで `menuOpen` をトグルし、モバイルメニューを開閉
 * - メニュー開時は `document.body` に `nav-open` クラスを付与してスクロールを制御
 * - ページ遷移（hashchange イベント）でメニューを自動的に閉じる
 */
export function NavBar() {
  const { session, logout, loading } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  /**
   * メニュー開閉に連動して body クラスを操作する副作用。
   * - menuOpen が true  → body に "nav-open" クラスを追加（背景スクロール防止など）
   * - menuOpen が false → "nav-open" クラスを除去
   * - クリーンアップ: コンポーネントアンマウント時に必ず "nav-open" を削除し、
   *   body スタイルが残り続けるのを防ぐ
   *
   * 依存配列: [menuOpen] — メニュー状態が変わった時だけ実行
   */
  useEffect(() => {
    document.body.classList.toggle("nav-open", menuOpen);
    return () => document.body.classList.remove("nav-open");
  }, [menuOpen]);

  /**
   * ハッシュ変更（SPA 内ページ遷移）でメニューを自動クローズする副作用。
   * アンカーリンクをタップしてページ内ジャンプした際にもメニューが
   * 残ったままにならないよう hashchange イベントを監視する。
   * - クリーンアップ: アンマウント時にリスナーを除去してメモリリークを防ぐ
   *
   * 依存配列: [] — マウント時に一度だけリスナーを登録
   */
  useEffect(() => {
    const close = () => setMenuOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, []);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

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
            <a
              key={link.href}
              href={link.href}
              className={isActive(link.href) ? "active" : ""}
              onClick={() => setMenuOpen(false)}
            >
              {link.label}
            </a>
          ))}

          {SAAS_ENABLED && !loading && session && (
            <>
              <a
                href="/settings"
                className={isActive("/settings") ? "active" : ""}
                onClick={() => setMenuOpen(false)}
              >
                設定
              </a>
              <span className="nav-plan-badge">
                {session.tenant.plan.toUpperCase()}
              </span>
              <button
                type="button"
                className="nav-logout"
                onClick={() => { setMenuOpen(false); logout(); }}
              >
                ログアウト
              </button>
            </>
          )}

          {SAAS_ENABLED && !loading && !session && (
            <>
              <a href="/login" onClick={() => setMenuOpen(false)}>ログイン</a>
              <a href="/register" className="nav-cta" onClick={() => setMenuOpen(false)}>
                無料登録
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
