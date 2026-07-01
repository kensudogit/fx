/**
 * @file analysis/page.tsx
 * @description マーケット分析ページ
 *
 * URL: /analysis
 *
 * 主要機能:
 * - 複数カテゴリのマーケット分析（センチメント・相関・ボラティリティ等）
 * - 通貨強弱・市場動向の可視化
 * - AnalysisDashboard コンポーネントへの委譲
 * - 利用には analysis_basic 機能フラグが必要
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import AnalysisDashboard from "@/components/AnalysisDashboard";

/**
 * AnalysisPage コンポーネント
 *
 * マーケット分析機能のエントリーポイントページ。
 * センチメント・相関・ボラティリティなど 5 カテゴリの分析 UI を提供する。
 * すべての描画ロジックは AnalysisDashboard コンポーネントに委譲している。
 *
 * @returns AnalysisDashboard コンポーネント
 */
export default function AnalysisPage() {
  return <AnalysisDashboard />;
}
