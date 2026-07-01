/**
 * @file pro/page.tsx
 * @description AI Pro ダッシュボードページ
 *
 * URL: /pro
 *
 * 主要機能:
 * - AI Pro プラン向けの高度な分析機能を 7 機能で提供
 * - マルチモデル AI 予測・詳細シグナル・バックテスト結果の表示
 * - AIProDashboard コンポーネントへの委譲
 * - 利用には ai_pro 機能フラグが必要（Pro 以上のプラン）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import AIProDashboard from "@/components/AIProDashboard";

/**
 * ProPage コンポーネント
 *
 * AI Pro 機能のエントリーポイントページ。
 * Pro プラン以上のユーザーが利用できる高度な AI 分析 UI を提供する。
 * すべての描画ロジックは AIProDashboard コンポーネントに委譲している。
 *
 * @returns AIProDashboard コンポーネント
 */
export default function ProPage() {
  return <AIProDashboard />;
}
