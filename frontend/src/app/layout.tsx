import type { Metadata } from "next";
import "./globals.css";

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
            </nav>
          </div>
        </header>
        <main>
          <div className="container">{children}</div>
        </main>
      </body>
    </html>
  );
}
