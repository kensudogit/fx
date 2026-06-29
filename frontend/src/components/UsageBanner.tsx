/**
 * React コンポーネント — UsageBanner
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { SAAS_ENABLED } from "@/lib/auth";
import { createBillingCheckout } from "@/lib/api";

export function UsageBanner() {
  const { session, loading } = useAuth();

  if (!SAAS_ENABLED || loading || !session) return null;

  const { usage, tenant } = session;
  const pct = usage.usage_percent ?? Math.round((usage.daily_calls / usage.daily_limit) * 100);
  const level = usage.usage_level ?? (pct >= 90 ? "critical" : pct >= 75 ? "warning" : "ok");

  if (level === "ok" && tenant.plan !== "free") return null;

  const handleUpgrade = async () => {
    try {
      const { checkout_url } = await createBillingCheckout("pro");
      window.location.href = checkout_url;
    } catch {
      window.location.href = "/pricing";
    }
  };

  return (
    <div className={`usage-banner usage-banner--${level}`}>
      <div className="usage-banner-inner">
        <div className="usage-banner-text">
          <strong>
            {level === "exhausted"
              ? "本日の API 上限に達しました"
              : level === "critical"
                ? "API 利用量が上限に近づいています"
                : level === "warning"
                  ? "API 利用量が増えています"
                  : `${tenant.plan.toUpperCase()} プラン`}
          </strong>
          <span>
            {usage.daily_calls.toLocaleString()} / {usage.daily_limit.toLocaleString()} 回
          </span>
        </div>
        <div className="usage-bar" aria-hidden>
          <div className="usage-bar-fill" style={{ width: `${Math.min(100, pct)}%` }} />
        </div>
        {(level !== "ok" || tenant.plan === "free") && (
          <div className="usage-banner-actions">
            {tenant.plan === "free" || level !== "ok" ? (
              <button type="button" className="usage-banner-btn" onClick={handleUpgrade}>
                Pro にアップグレード
              </button>
            ) : null}
            <Link href="/settings" className="usage-banner-link">
              設定
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
