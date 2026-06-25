"use client";

import { useEffect, useState } from "react";
import { getBillingPlans, type BillingPlan } from "@/lib/api";
import Link from "next/link";

export default function PricingPage() {
  const [plans, setPlans] = useState<BillingPlan[]>([]);

  useEffect(() => {
    getBillingPlans().then((r) => setPlans(r.plans));
  }, []);

  return (
    <>
      <div className="page-header">
        <h1>料金プラン</h1>
        <Link href="/register" className="btn">
          無料で始める
        </Link>
      </div>
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
              {p.features.oanda_orders && <li>OANDA 注文</li>}
              <li>APIキー {String(p.features.api_keys)} 本</li>
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}
