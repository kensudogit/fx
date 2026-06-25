import type { Metadata, Viewport } from "next";
import "./globals.css";
import { UsageGuidePanel } from "@/components/UsageGuidePanel";
import { AuthProvider } from "@/context/AuthContext";
import { NavBar } from "@/components/NavBar";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#0f1419",
};

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
