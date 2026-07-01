/**
 * @file ai/page.tsx
 * @description AI 分析ページ
 *
 * URL: /ai
 *
 * 主要機能:
 * - OpenAI を活用した FX 市場の AI 統合分析
 * - 通貨ペアごとの AI 予測・シグナル表示
 * - AIDashboard コンポーネントへの委譲
 * - 利用にはプランの ai 機能フラグが必要
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import AIDashboard from "@/components/AIDashboard";

/**
 * AIPage コンポーネント
 *
 * AI 分析機能のエントリーポイントページ。
 * OpenAI を利用した市場分析・シグナル生成の UI を提供する。
 * すべての描画ロジックは AIDashboard コンポーネントに委譲している。
 *
 * @returns AIDashboard コンポーネント
 */
export default function AIPage() {
  return <AIDashboard />;
}
