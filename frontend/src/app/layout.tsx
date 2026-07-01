/**
 * @file layout.tsx
 * @description アプリケーション全体のルートレイアウト
 *
 * URL: 全ページ共通（Next.js App Router のルートレイアウト）
 *
 * 主要機能:
 * - ビューポート・メタデータの設定（SEO・PWA 対応）
 * - 認証コンテキスト（AuthProvider）のアプリ全体への提供
 * - ナビゲーションバー（NavBar）の常時表示
 * - API 利用量バナー（UsageBanner）の常時表示
 * - モバイル向けクイックドック（MobileQuickDock）の常時表示
 * - 使い方ガイドパネル（UsageGuidePanel）の常時表示
 * - PWA マニフェスト参照・Apple Web App 設定
 */

import type { Metadata, Viewport } from "next";
import "./globals.css";
import { UsageGuidePanel } from "@/components/UsageGuidePanel";
import { UsageBanner } from "@/components/UsageBanner";
import { MobileQuickDock } from "@/components/MobileQuickDock";
import { AuthProvider } from "@/context/AuthContext";
import { NavBar } from "@/components/NavBar";

/**
 * ビューポート設定
 * - モバイルデバイスでの表示最適化
 * - ピンチズーム最大倍率 5x まで許可
 * - iOS のノッチ領域まで表示を拡張する "cover" フィット
 * - ステータスバー・ブラウザ UI のテーマカラーを指定
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#0f1419",
};

/**
 * Next.js メタデータ設定
 * - ページタイトルと説明文（SEO 用）
 * - Apple Web App（ホーム画面追加）対応設定
 * - 電話番号の自動リンク変換を無効化
 * - PWA マニフェストファイル参照
 */
export const metadata: Metadata = {
  title: "FX Tool - テクニカル・ファンダメンタル分析",
  description: "FX通貨ペアのテクニカル分析・ファンダメンタル分析ツール",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "FX Tool",
  },
  formatDetection: {
    telephone: false,
  },
  manifest: "/manifest.json",
};

/**
 * RootLayout コンポーネント
 *
 * Next.js App Router のルートレイアウト。全ページを囲む共通 UI を定義する。
 * AuthProvider でアプリ全体に認証状態を配布し、
 * ナビゲーション・バナー・モバイルドック・ガイドパネルを常時レンダリングする。
 *
 * @param children - 各ページのコンテンツ（Next.js により自動的に渡される）
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        {/* 認証状態をアプリ全体に提供するコンテキストプロバイダー */}
        <AuthProvider>
          {/* グローバルナビゲーションバー（ページ上部固定） */}
          <NavBar />
          {/* API 利用量が上限に近づいたときに表示する警告バナー */}
          <UsageBanner />
          {/* 各ページのメインコンテンツ領域 */}
          <main>
            <div className="container">{children}</div>
          </main>
          {/* モバイル向けの下部クイックナビゲーションドック */}
          <MobileQuickDock />
          {/* 右側に表示されるスライドアウト型の使い方ガイドパネル */}
          <UsageGuidePanel />
        </AuthProvider>
      </body>
    </html>
  );
}
