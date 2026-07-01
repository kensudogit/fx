/**
 * @file page.tsx
 * @description トップページ（テクニカル分析ダッシュボード）
 *
 * URL: /
 *
 * 主要機能:
 * - FX 通貨ペアのテクニカル分析チャートを表示
 * - 移動平均・RSI・MACD 等のテクニカル指標の可視化
 * - TechnicalDashboard コンポーネントへの委譲
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import TechnicalDashboard from "@/components/TechnicalDashboard";

/**
 * Home コンポーネント（トップページ）
 *
 * サイトのルートページ。テクニカル分析ダッシュボードを表示する。
 * すべての描画ロジックは TechnicalDashboard コンポーネントに委譲している。
 *
 * @returns TechnicalDashboard コンポーネント
 */
export default function Home() {
  return <TechnicalDashboard />;
}
