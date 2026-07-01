/**
 * @file pricing/page.tsx
 * @description 料金プランページ
 *
 * URL: /pricing
 *
 * 主要機能:
 * - 利用可能な全プラン（Free / Pro / Enterprise 等）の一覧表示
 * - 月額料金・API 日次上限・機能フラグの比較カード
 * - Stripe 決済が有効な場合は Stripe Checkout へリダイレクト
 * - 未ログインユーザーを新規登録ページへ誘導
 * - Stripe 無効時は設定ページのプラン選択へフォールバック
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useState } from "react";
import { createBillingCheckout, getBillingPlans, type BillingPlan } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import Link from "next/link";

/**
 * PricingPage コンポーネント
 *
 * 料金プランの比較・申込ページ。
 * 初期表示時に利用可能なプラン一覧と Stripe 有効フラグを API から取得し、
 * カード形式で機能比較を表示する。
 * 申込ボタン押下時は認証状態・Stripe 設定に応じて遷移先を切り替える。
 */
export default function PricingPage() {
  // API から取得した全プランの配列
  const [plans, setPlans] = useState<BillingPlan[]>([]);

  // Stripe 決済が有効かどうかを示すフラグ（バックエンド設定に依存）
  const [stripeEnabled, setStripeEnabled] = useState(false);

  // 現在のログインセッション（未ログイン時は null）
  const { session } = useAuth();

  /**
   * 初回マウント時に課金プラン情報を取得する
   * - getBillingPlans(): GET /api/billing/plans — プラン一覧と Stripe 有効フラグを返す
   */
  useEffect(() => {
    getBillingPlans().then((r) => {
      setPlans(r.plans);
      setStripeEnabled(Boolean(r.stripe_enabled));
    });
  }, []);

  /**
   * プラン申込ボタンのクリックハンドラー
   *
   * ビジネスロジック:
   * 1. 未ログインユーザー → /register へリダイレクト
   * 2. Free プランが選択された場合 → 何もしない（無料なので手続き不要）
   * 3. Stripe 有効 → createBillingCheckout で Stripe Checkout URL を取得しリダイレクト
   * 4. Stripe 無効 → /settings のプラン選択画面へリダイレクト
   *
   * @param planId - 申込対象のプラン ID（"free" | "pro" | "enterprise" 等）
   */
  const handleCheckout = async (planId: string) => {
    // 未ログインの場合は新規登録ページへ誘導
    if (!session) {
      window.location.href = "/register";
      return;
    }
    // Free プランは申込処理不要のため早期リターン
    if (planId === "free") return;
    if (stripeEnabled) {
      // POST /api/billing/checkout でプラン ID に対応する Stripe Checkout URL を取得
      const { checkout_url } = await createBillingCheckout(planId);
      // Stripe の決済ページへリダイレクト
      window.location.href = checkout_url;
      return;
    }
    // Stripe が無効な場合は設定ページでプランを選択させる
    window.location.href = "/settings";
  };

  return (
    <>
      <div className="page-header">
        <h1>料金プラン</h1>
        {/* 未ログインユーザーを新規登録へ誘導するCTAボタン */}
        <Link href="/register" className="btn">
          無料で始める
        </Link>
      </div>
      {/* Stripe が有効な場合のみ安全な決済方法の案内を表示 */}
      {stripeEnabled && <p className="hint">有料プランは Stripe で安全に決済できます。</p>}
      {/* プランカードグリッド: API から取得したプランをループしてカード表示 */}
      <div className="plan-grid pricing-grid">
        {plans.map((p) => (
          <div key={p.id} className="card plan-card">
            <h2>{p.name}</h2>
            {/* 月額料金表示 */}
            <p className="plan-price">${p.price_monthly_usd}/月</p>
            {/* API 日次利用上限を 3 桁区切りで表示 */}
            <p className="hint">API {p.daily_api_limit.toLocaleString()} 回/日</p>
            {/* プランに含まれる機能フラグを条件付きリスト表示 */}
            <ul className="headline-list">
              <li>テクニカル・ファンダメンタル分析</li>
              {/* analysis_basic フラグが true の場合のみ表示 */}
              {p.features.analysis_basic && <li>マーケット分析（5カテゴリ）</li>}
              {/* ai フラグが true の場合のみ表示 */}
              {p.features.ai && <li>OpenAI 統合分析</li>}
              {/* ai_pro フラグが true の場合のみ表示 */}
              {p.features.ai_pro && <li>AI Pro（7機能）</li>}
              {/* oanda_orders フラグが true の場合のみ表示 */}
              {p.features.oanda_orders && <li>OANDA 口座（テナント別）</li>}
              {/* autotrade フラグが true の場合のみ表示 */}
              {p.features.autotrade && <li>自動取引エンジン</li>}
              {/* analysis_intelligence フラグが true の場合のみ表示 */}
              {p.features.analysis_intelligence && <li>統合インテリジェンス</li>}
              {/* 発行可能な API キー本数を表示 */}
              <li>APIキー {String(p.features.api_keys)} 本</li>
            </ul>
            {/* Free プランは申込ボタン不要のため非表示 */}
            {p.id !== "free" && (
              <button type="button" className="btn-secondary" onClick={() => handleCheckout(p.id)}>
                {/* ボタンラベル: Stripe 有効 → "Stripeで申込" / ログイン済み → "設定で選択" / 未ログイン → "登録して申込" */}
                {stripeEnabled ? "Stripeで申込" : session ? "設定で選択" : "登録して申込"}
              </button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
