import type { Metadata } from "next";
import "./globals.css";
import { UsageGuidePanel } from "@/components/UsageGuidePanel";
import { AuthProvider } from "@/context/AuthContext";
import { NavBar } from "@/components/NavBar";

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
        <AuthProvider>
          <NavBar />
          <main>
            <div className="container">{children}</div>
          </main>
          <UsageGuidePanel />
        </AuthProvider>
      </body>
    </html>
  );
}
