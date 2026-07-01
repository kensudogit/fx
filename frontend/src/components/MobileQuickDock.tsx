/**
 * @file MobileQuickDock.tsx
 * @description モバイル向けクイックナビゲーションドック
 *
 * 画面下部に固定表示されるモバイル専用のタブバー。
 * 主要ページへのショートカットリンクをアイコン＋ラベルで提供し、
 * 現在のパスに対応するアイテムをハイライト表示する。
 * デスクトップでは CSS で非表示になることを前提とした実装。
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * ドックに表示するナビリンクの定義リスト。
 * - href: 遷移先パス
 * - label: モバイルドック上のラベル文字列
 * - short: アイコン代わりに使う短縮文字・絵文字
 */
const DOCK_LINKS = [
  { href: "/", label: "分析", short: "FX" },
  { href: "/analysis", label: "総合", short: "5" },
  { href: "/autotrade", label: "自動", short: "⚡" },
  { href: "/ai", label: "AI", short: "AI" },
  { href: "/settings", label: "設定", short: "⚙" },
] as const;

/**
 * MobileQuickDock
 *
 * モバイル画面の下部に固定表示されるクイックドックコンポーネント。
 * `usePathname` で現在の URL パスを取得し、一致するリンクに
 * `is-active` クラスを付与してアクティブ状態を示す。
 *
 * アクティブ判定ルール:
 *  - ルートパス "/"  → 完全一致のみ
 *  - それ以外       → `startsWith` でネストされたパスも一致と判定
 */
export function MobileQuickDock() {
  // 現在表示されているページのパス名を取得（SSR 非対応のためクライアント限定）
  const pathname = usePathname();

  return (
    /* role="navigation" に相当する <nav> でアクセシビリティを確保 */
    <nav className="mobile-quick-dock" aria-label="クイックナビ">
      {DOCK_LINKS.map((link) => {
        /*
         * アクティブ判定:
         *  - "/" は完全一致のみ（他ページが誤ってハイライトされるのを防ぐ）
         *  - その他は前方一致で、サブページ（例: /analysis/detail）にも対応
         */
        const active = pathname === link.href || (link.href !== "/" && pathname.startsWith(link.href));
        return (
          <Link
            key={link.href}
            href={link.href}
            /* アクティブ時は is-active クラスを追加してスタイルを切り替え */
            className={`mobile-dock-item${active ? " is-active" : ""}`}
          >
            {/* アイコン代わりの短縮文字・絵文字（視覚的な識別子） */}
            <span className="mobile-dock-icon">{link.short}</span>
            {/* ラベルテキスト（小さなフォントでアイコン下部に表示） */}
            <span className="mobile-dock-label">{link.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
