import type { Metadata } from "next";
import "./globals.css";
import { UsageGuidePanel } from "@/components/UsageGuidePanel";

export const metadata: Metadata = {
  title: "FX Tool - テクニカル・ファンダメンタル分析",
  description: "FX通貨ペアのテクニカル分析・ファンダメンタル分析ツール",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <header>
          <div className="container">
            <a href="/" className="logo">
              FX Tool
            </a>
            <nav>
              <a href="/">テクニカル分析</a>
              <a href="/fundamental">ファンダメンタル分析</a>
              <a href="/ai">AI分析</a>
              <a href="/dashboard">統合ダッシュボード</a>
            </nav>
          </div>
        </header>
        <main>
          <div className="container">{children}</div>
        </main>
        <UsageGuidePanel />
      </body>
    </html>
  );
}
