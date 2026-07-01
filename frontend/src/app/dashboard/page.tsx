/**
 * @file dashboard/page.tsx
 * @description 統合ダッシュボードページ
 *
 * URL: /dashboard
 *
 * 主要機能:
 * - テクニカル・AI・マーケット分析を横断した統合ビュー
 * - 主要通貨ペアのサマリー情報を一覧表示
 * - IntegrationDashboard コンポーネントへの委譲
 * - 複数機能を組み合わせたプレミアムダッシュボード
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import IntegrationDashboard from "@/components/IntegrationDashboard";

/**
 * DashboardPage コンポーネント
 *
 * 統合ダッシュボードのエントリーポイントページ。
 * テクニカル分析・AI 予測・マーケット分析を 1 画面で俯瞰できる UI を提供する。
 * すべての描画ロジックは IntegrationDashboard コンポーネントに委譲している。
 *
 * @returns IntegrationDashboard コンポーネント
 */
export default function DashboardPage() {
  return <IntegrationDashboard />;
}
