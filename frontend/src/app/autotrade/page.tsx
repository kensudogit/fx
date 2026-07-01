/**
 * @file autotrade/page.tsx
 * @description 自動取引ページ
 *
 * URL: /autotrade
 *
 * 主要機能:
 * - OANDA API を利用した自動取引エンジンの操作 UI
 * - ストラテジー設定・注文管理・ポジション確認
 * - AutoTradePanel コンポーネントへの委譲
 * - 利用には autotrade 機能フラグおよび OANDA 口座設定が必要
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import AutoTradePanel from "@/components/AutoTradePanel";

/**
 * AutoTradePage コンポーネント
 *
 * 自動取引機能のエントリーポイントページ。
 * OANDA への注文送信・ポジション管理・ストラテジー設定 UI を提供する。
 * すべての描画ロジックは AutoTradePanel コンポーネントに委譲している。
 *
 * @returns AutoTradePanel コンポーネント
 */
export default function AutoTradePage() {
  return <AutoTradePanel />;
}
