/**
 * @file UsageBanner.tsx
 * @description API 使用量バナーコンポーネント
 *
 * ユーザーの API 使用量（日次呼び出し数）を視覚的に表示し、
 * 上限に近づいた際に警告・アップグレード誘導を行うバナー。
 * 画面上部（または下部）に固定表示され、以下の状況で表示される：
 * - free プランのユーザー（常時表示）
 * - 使用量が 75% 以上の有料プランユーザー
 *
 * SaaS モード（SAAS_ENABLED）が無効の場合は常に非表示。
 */

"use client";

import Link from "next/link";
import { useAuth } from "@/context/AuthContext";
import { SAAS_ENABLED } from "@/lib/auth";
import { createBillingCheckout } from "@/lib/api";

/**
 * UsageBanner
 *
 * 認証済みユーザーの API 使用量を帯グラフと数値で表示し、
 * 使用レベルに応じたアクションボタン（アップグレード・設定リンク）を提供する。
 *
 * ### 表示条件
 * - `SAAS_ENABLED` が false → 非表示（SaaS 機能未有効時）
 * - `loading` が true     → 非表示（セッション取得中）
 * - `session` が null     → 非表示（未ログイン時）
 * - 上記以外で `level === "ok"` かつ `plan !== "free"` → 非表示（十分な残量がある有料ユーザー）
 *
 * ### 使用レベルの判定ロジック
 * バックエンドが `usage_level` を返す場合はそれを優先し、
 * 未提供の場合はフロントエンドで `usage_percent` から算出する：
 * - 90% 以上 → "critical"（緊急: API が枯渇しそう）
 * - 75% 以上 → "warning"（警告: 使用量が増えている）
 * - それ未満 → "ok"（通常: 問題なし）
 * - バックエンドが "exhausted" を返す場合 → 上限到達済み
 *
 * ### アップグレードフロー
 * 1. 「Pro にアップグレード」ボタンをクリック
 * 2. `createBillingCheckout("pro")` で Stripe Checkout セッションを作成
 * 3. 取得した checkout_url にリダイレクト
 * 4. 失敗時は /pricing ページにフォールバック
 */
export function UsageBanner() {
  // 認証コンテキストからセッション情報とローディング状態を取得
  const { session, loading } = useAuth();

  /*
   * 早期リターン条件:
   * - SaaS 機能が無効: バナー自体不要
   * - セッション取得中: ハイドレーション不一致を防ぐため非表示
   * - 未ログイン: 使用量情報がないため表示不可
   */
  if (!SAAS_ENABLED || loading || !session) return null;

  const { usage, tenant } = session;

  /*
   * 使用量パーセンテージの算出。
   * バックエンドが usage_percent を提供している場合はそれを使用し、
   * ない場合は daily_calls / daily_limit で計算（小数以下は切り捨て）。
   */
  const pct = usage.usage_percent ?? Math.round((usage.daily_calls / usage.daily_limit) * 100);

  /*
   * 使用レベルの判定。
   * バックエンドの usage_level を優先し、未提供の場合はパーセントから算出。
   * - "exhausted": 上限到達（バックエンドのみ）
   * - "critical" : 90% 以上
   * - "warning"  : 75% 以上
   * - "ok"       : 75% 未満
   */
  const level = usage.usage_level ?? (pct >= 90 ? "critical" : pct >= 75 ? "warning" : "ok");

  // 有料プランで使用量が通常レベル（ok）の場合はバナーを非表示
  if (level === "ok" && tenant.plan !== "free") return null;

  /**
   * Stripe Checkout セッションを作成してアップグレードページへリダイレクトする。
   * API 失敗時は静的な料金ページ（/pricing）に遷移してエラーを隠蔽する。
   */
  const handleUpgrade = async () => {
    try {
      // バックエンドに Pro プランのチェックアウトセッション作成をリクエスト
      const { checkout_url } = await createBillingCheckout("pro");
      // 取得した Stripe Checkout URL にリダイレクト
      window.location.href = checkout_url;
    } catch {
      // Checkout セッション作成失敗時は料金ページにフォールバック
      window.location.href = "/pricing";
    }
  };

  return (
    /*
     * バナーのルート要素。
     * `usage-banner--${level}` で使用レベルに応じた CSS スタイルを適用：
     * - usage-banner--ok       : 通常（free プランのみ表示）
     * - usage-banner--warning  : 黄色系の警告スタイル
     * - usage-banner--critical : 赤系の緊急スタイル
     * - usage-banner--exhausted: 最も強い警告スタイル
     */
    <div className={`usage-banner usage-banner--${level}`}>
      <div className="usage-banner-inner">
        {/* テキストエリア: 使用レベルに応じたメッセージと使用数/上限 */}
        <div className="usage-banner-text">
          <strong>
            {/*
             * 使用レベルに応じたメインメッセージを表示:
             * - exhausted: 上限到達
             * - critical : 上限に近づいている警告
             * - warning  : 増加傾向の注意
             * - ok（free プランのみ）: プラン名表示
             */}
            {level === "exhausted"
              ? "本日の API 上限に達しました"
              : level === "critical"
                ? "API 利用量が上限に近づいています"
                : level === "warning"
                  ? "API 利用量が増えています"
                  : `${tenant.plan.toUpperCase()} プラン`}
          </strong>
          {/* 日次使用数 / 日次上限の数値表示（桁区切り付き）*/}
          <span>
            {usage.daily_calls.toLocaleString()} / {usage.daily_limit.toLocaleString()} 回
          </span>
        </div>

        {/*
         * 使用量プログレスバー。
         * aria-hidden="true" でスクリーンリーダーには非表示（数値テキストで代替）。
         * width を pct% にクランプ（最大 100% で溢れ防止）。
         */}
        <div className="usage-bar" aria-hidden>
          <div className="usage-bar-fill" style={{ width: `${Math.min(100, pct)}%` }} />
        </div>

        {/*
         * アクションエリア: 警告レベルまたは free プランのユーザーに表示。
         * - Pro アップグレードボタン
         * - 設定ページへのリンク
         */}
        {(level !== "ok" || tenant.plan === "free") && (
          <div className="usage-banner-actions">
            {/* アップグレードボタン: free プランまたは ok 以外のレベルで表示 */}
            {tenant.plan === "free" || level !== "ok" ? (
              <button type="button" className="usage-banner-btn" onClick={handleUpgrade}>
                Pro にアップグレード
              </button>
            ) : null}
            {/* 設定ページへのリンク: 使用量の詳細確認・プラン管理に遷移 */}
            <Link href="/settings" className="usage-banner-link">
              設定
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
