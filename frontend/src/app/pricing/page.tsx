/**
 * Next.js ページ — page
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useState } from "react";
import { createBillingCheckout, getBillingPlans, type BillingPlan } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import Link from "next/link";

export default function PricingPage() {
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [stripeEnabled, setStripeEnabled] = useState(false);
  const { session } = useAuth();

  useEffect(() => {
    getBillingPlans().then((r) => {
      setPlans(r.plans);
      setStripeEnabled(Boolean(r.stripe_enabled));
    });
  }, []);

  const handleCheckout = async (planId: string) => {
    if (!session) {
      window.location.href = "/register";
      return;
    }
    if (planId === "free") return;
    if (stripeEnabled) {
      const { checkout_url } = await createBillingCheckout(planId);
      window.location.href = checkout_url;
      return;
    }
    window.location.href = "/settings";
  };

  return (
    <>
      <div className="page-header">
        <h1>料金プラン</h1>
        <Link href="/register" className="btn">
          無料で始める
        </Link>
      </div>
      {stripeEnabled && <p className="hint">有料プランは Stripe で安全に決済できます。</p>}
      <div className="plan-grid pricing-grid">
        {plans.map((p) => (
          <div key={p.id} className="card plan-card">
            <h2>{p.name}</h2>
            <p className="plan-price">${p.price_monthly_usd}/月</p>
            <p className="hint">API {p.daily_api_limit.toLocaleString()} 回/日</p>
            <ul className="headline-list">
              <li>テクニカル・ファンダメンタル分析</li>
              {p.features.analysis_basic && <li>マーケット分析（5カテゴリ）</li>}
              {p.features.ai && <li>OpenAI 統合分析</li>}
              {p.features.ai_pro && <li>AI Pro（7機能）</li>}
              {p.features.oanda_orders && <li>OANDA 口座（テナント別）</li>}
              {p.features.autotrade && <li>自動取引エンジン</li>}
              {p.features.analysis_intelligence && <li>統合インテリジェンス</li>}
              <li>APIキー {String(p.features.api_keys)} 本</li>
            </ul>
            {p.id !== "free" && (
              <button type="button" className="btn-secondary" onClick={() => handleCheckout(p.id)}>
                {stripeEnabled ? "Stripeで申込" : session ? "設定で選択" : "登録して申込"}
              </button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
