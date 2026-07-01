/**
 * @file settings/page.tsx
 * @description 設定・課金管理ページ
 *
 * URL: /settings
 *
 * 主要機能:
 * - ワークスペース情報・現在のプラン・API 利用量メーターの表示
 * - プラン変更（Stripe Checkout または即時アップグレード）
 * - Stripe 請求ポータルへのアクセス
 * - OANDA API トークン・口座 ID・環境（practice/live）の設定保存
 * - API キー発行（TradingView Webhook や外部連携用）と一覧表示
 * - Stripe 決済完了後の URL パラメータ（?checkout=success）検出とプラン反映
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useEffect, useState } from "react";
import {
  createApiKey,
  createBillingCheckout,
  createBillingPortal,
  getBillingPlans,
  getOandaSettings,
  listApiKeys,
  updateOandaSettings,
  upgradePlan,
  type BillingPlan,
} from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { setApiKey } from "@/lib/auth";

/**
 * SettingsPage コンポーネント
 *
 * 設定・課金管理のメインページ。
 * ワークスペース情報・プラン変更・OANDA 設定・API キー管理を
 * 1 ページで提供するコントロールパネル。
 * 未認証時（session が null）はローディング表示を返す。
 */
export default function SettingsPage() {
  // 現在のログインセッション（テナント情報・利用量・ユーザー情報を含む）と
  // セッション更新関数（プラン変更後のリフレッシュに使用）
  const { session, refresh } = useAuth();

  // API から取得した全プランの配列
  const [plans, setPlans] = useState<BillingPlan[]>([]);

  // Stripe 決済が有効かどうかを示すフラグ（バックエンド設定に依存）
  const [stripeEnabled, setStripeEnabled] = useState(false);

  // 発行済み API キーの一覧（ID・名前・プレフィックスを含む）
  const [keys, setKeys] = useState<{ id: number; name: string; key_prefix: string }[]>([]);

  // 新規 API キー発行時の名前入力値（デフォルト: TradingView Webhook）
  const [newKeyName, setNewKeyName] = useState("TradingView Webhook");

  // 新規発行した API キーの完全な文字列（再表示不可のため発行直後のみ表示）
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  // 操作成功時に表示するメッセージ（null = メッセージなし）
  const [message, setMessage] = useState<string | null>(null);

  // 操作失敗時に表示するエラーメッセージ（null = エラーなし）
  const [error, setError] = useState<string | null>(null);

  // OANDA 口座 ID の入力値（例: "101-001-XXXXXXX-001"）
  const [oandaAccountId, setOandaAccountId] = useState("");

  // OANDA API トークンの入力値（新規入力時のみ、保存済みはマスク表示）
  const [oandaToken, setOandaToken] = useState("");

  // OANDA 接続環境: "practice"（デモ口座）または "live"（本番口座）
  const [oandaEnv, setOandaEnv] = useState<"practice" | "live">("practice");

  // OANDA 口座の接続状態サマリー（モード・残高・データソース等）
  const [oandaSummary, setOandaSummary] = useState<string | null>(null);

  /**
   * 初回マウント時にページ表示に必要なデータを並行取得する
   * - getBillingPlans(): GET /api/billing/plans — プラン一覧と Stripe 有効フラグ
   * - listApiKeys(): GET /api/auth/api-keys — 発行済み API キー一覧
   * - getOandaSettings(): GET /api/oanda/settings — OANDA 口座設定と接続状態
   *
   * OANDA 設定取得時:
   * - 保存済みの account_id をフォームに復元
   * - 環境設定（live/practice）をフォームに復元
   * - 接続済みの場合はモード・残高・データソースを oandaSummary に格納
   * - 未設定の場合はサーバーから返されたメッセージを表示
   */
  useEffect(() => {
    // プラン一覧と Stripe 有効フラグを取得
    getBillingPlans().then((r) => {
      setPlans(r.plans);
      setStripeEnabled(Boolean(r.stripe_enabled));
    });
    // 発行済み API キー一覧を取得（未ログインや権限不足の場合は静かに失敗）
    listApiKeys().then((r) => setKeys(r.keys)).catch(() => {});
    // OANDA 設定と口座の接続状態を取得
    getOandaSettings()
      .then((r) => {
        // 保存済みの口座 ID をフォームに反映
        if (r.settings?.account_id) setOandaAccountId(r.settings.account_id);
        // 保存済みの環境設定をフォームに反映（live のみ明示的に設定、デフォルトは practice）
        if (r.settings?.environment === "live") setOandaEnv("live");
        if (r.account_summary?.configured) {
          // 接続設定済みの場合: モード・残高・データソースを整形して表示
          setOandaSummary(
            `${r.account_summary.mode} · $${r.account_summary.balance.toLocaleString()} (${r.account_summary.source})`,
          );
        } else {
          // 未設定の場合: サーバーから返されたメッセージ（または null）を表示
          setOandaSummary(r.account_summary?.message ?? null);
        }
      })
      .catch(() => {});
  }, []);

  /**
   * Stripe 決済完了後の URL パラメータを検出してプランを反映する
   * Stripe Checkout から ?checkout=success パラメータ付きでリダイレクトされた場合、
   * 完了メッセージを表示し、認証コンテキストをリフレッシュしてプランを最新化する
   *
   * refresh が変化するたびに再実行（refresh 関数の参照が安定している想定）
   */
  useEffect(() => {
    // SSR 時（window が未定義の場合）は処理をスキップ
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    // Stripe 決済完了を示すクエリパラメータが存在する場合
    if (params.get("checkout") === "success") {
      setMessage("Stripe 決済が完了しました。プランを反映中...");
      // セッション情報（プラン・利用量）を最新状態に更新
      refresh();
    }
  }, [refresh]);

  /**
   * Stripe 請求ポータルを開くハンドラー
   * POST /api/billing/portal で Stripe カスタマーポータルの URL を取得し
   * そのページへリダイレクトする（請求書確認・サブスクリプション管理が可能）
   */
  const handlePortal = async () => {
    setError(null);
    try {
      // POST /api/billing/portal — Stripe 請求ポータルの URL を取得
      const { portal_url } = await createBillingPortal();
      window.location.href = portal_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "請求ポータルを開けません");
    }
  };

  /**
   * API 利用量のパーセンテージを計算する
   * - セッションに usage_percent が含まれる場合はそれを優先使用
   * - 含まれない場合は daily_calls / daily_limit で計算して四捨五入
   * - セッション未取得時は 0 を返す
   */
  const usagePct =
    session?.usage.usage_percent ??
    (session ? Math.round((session.usage.daily_calls / session.usage.daily_limit) * 100) : 0);

  /**
   * プランアップグレード（またはダウングレード）ハンドラー
   *
   * ビジネスロジック:
   * 1. Stripe 有効 かつ Free 以外のプラン → Stripe Checkout へリダイレクト
   * 2. Stripe 無効 または Free プランへの変更 → upgradePlan API で即時変更
   * いずれの場合も成功後にセッションをリフレッシュしてプランを最新化する
   *
   * @param plan - 変更先のプラン ID（"free" | "pro" | "enterprise" 等）
   */
  const handleUpgrade = async (plan: string) => {
    setError(null);
    try {
      if (stripeEnabled && plan !== "free") {
        // Stripe 有効時は POST /api/billing/checkout で Checkout URL を取得してリダイレクト
        const { checkout_url } = await createBillingCheckout(plan);
        window.location.href = checkout_url;
        return;
      }
      // Stripe 無効時または Free への変更は POST /api/billing/upgrade で即時反映
      await upgradePlan(plan);
      setMessage(`${plan} プランに変更しました`);
      // セッション情報（プラン・利用量）を最新状態に更新
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "プラン変更に失敗しました");
    }
  };

  /**
   * OANDA 設定の保存ハンドラー
   *
   * 入力された口座 ID・API トークン・環境を
   * PUT /api/oanda/settings に送信して保存する。
   * 保存後は API トークン入力欄をリセット（セキュリティのため再表示しない）し、
   * 最新の接続状態を再取得して oandaSummary を更新する。
   */
  const handleSaveOanda = async () => {
    setError(null);
    try {
      // PUT /api/oanda/settings — 口座 ID・API トークン・環境を送信
      await updateOandaSettings({
        account_id: oandaAccountId,
        // トークンが空の場合は送信しない（既存の保存済みトークンを上書きしない）
        api_token: oandaToken || undefined,
        environment: oandaEnv,
      });
      // セキュリティのためトークン入力欄をクリア（保存済みトークンは再表示しない）
      setOandaToken("");
      setMessage("OANDA 設定を保存しました");
      // 保存後の接続状態を再取得して表示を更新
      const r = await getOandaSettings();
      if (r.account_summary?.configured) {
        setOandaSummary(
          `${r.account_summary.mode} · $${r.account_summary.balance.toLocaleString()} (${r.account_summary.source})`,
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "OANDA 設定の保存に失敗しました");
    }
  };

  /**
   * API キー新規発行ハンドラー
   *
   * 入力された名前で API キーを発行し、発行直後のみ完全なキー文字列を表示する。
   * キーは作成後に再表示できないため、ユーザーがブラウザへの保存を選択できるようにする。
   * 発行後はキー一覧を再取得して表示を更新する。
   *
   * POST /api/auth/api-keys にキー名を送信し、完全なキー文字列を受け取る
   */
  const handleCreateKey = async () => {
    setError(null);
    setCreatedKey(null);
    try {
      // POST /api/auth/api-keys — キー名を送信して新しい API キーを発行
      const res = await createApiKey(newKeyName);
      // 発行直後のみ完全なキー文字列を表示（再表示不可のため）
      setCreatedKey(res.api_key);
      // キー一覧を再取得して最新の発行済みキー一覧を反映
      setKeys(await listApiKeys().then((r) => r.keys));
    } catch (e) {
      setError(e instanceof Error ? e.message : "APIキー作成に失敗しました");
    }
  };

  // セッション未取得（認証確認中）の場合はローディング表示を返す
  if (!session) {
    return <div className="loading">読み込み中...</div>;
  }

  return (
    <>
      <div className="page-header">
        <h1>設定・課金</h1>
      </div>

      {/* 上段グリッド: ワークスペース情報（左）/ プラン変更（右） */}
      <div className="grid-2">
        {/* 左カード: ワークスペース情報・利用量・Stripe 請求ポータル */}
        <div className="card">
          <h2>ワークスペース</h2>
          {/* テナント名・スラッグの表示 */}
          <p>
            <strong>{session.tenant.name}</strong>（{session.tenant.slug}）
          </p>
          {/* 現在のプランバッジ・Stripe 契約中バッジ */}
          <p>
            プラン: <span className="badge badge-neutral">{session.tenant.plan.toUpperCase()}</span>
            {/* Stripe のサブスクリプションが存在する場合のみ契約中バッジを表示 */}
            {session.billing?.stripe_subscription && (
              <span className="badge badge-buy" style={{ marginLeft: "0.5rem" }}>
                Stripe契約中
              </span>
            )}
          </p>
          {/* API 利用量メーター: usagePct（0〜100）を視覚的なプログレスバーで表示 */}
          <div className="usage-meter">
            <div className="usage-meter-label">
              本日の API 利用 ({usagePct}%)
            </div>
            <div className="usage-bar">
              {/* 利用率が 100% を超えた場合は 100% に制限して表示 */}
              <div className="usage-bar-fill" style={{ width: `${Math.min(100, usagePct)}%` }} />
            </div>
          </div>
          {/* API 利用数の詳細（利用済み / 上限・残り回数） */}
          <div className="stat-grid">
            <div className="stat-item">
              <div className="label">本日のAPI利用</div>
              <div className="value">
                {session.usage.daily_calls} / {session.usage.daily_limit}
              </div>
            </div>
            <div className="stat-item">
              <div className="label">残り</div>
              <div className="value">{session.usage.remaining}</div>
            </div>
          </div>
          {/* ログイン中のメールアドレスを表示 */}
          <p className="hint">ログイン: {session.user.email}</p>
          {/* Stripe 有効 かつ Stripe カスタマーが存在する場合のみポータルボタンを表示 */}
          {stripeEnabled && session.billing?.stripe_customer && (
            <button type="button" className="btn-secondary" onClick={handlePortal}>
              Stripe 請求ポータル
            </button>
          )}
        </div>

        {/* 右カード: プラン変更・アップグレード */}
        <div className="card">
          <h2>プラン</h2>
          {/* Stripe 有効時のみ Stripe Checkout 使用の案内を表示 */}
          {stripeEnabled && <p className="hint">有料プランは Stripe Checkout で決済されます。</p>}
          {/* 操作成功メッセージ */}
          {message && <p className="hint">{message}</p>}
          {/* 操作失敗エラーメッセージ */}
          {error && <p className="error-text">{error}</p>}
          {/* プランカードグリッド: 現在のプランをアクティブ状態で強調表示 */}
          <div className="plan-grid">
            {plans.map((p) => (
              <div key={p.id} className={`plan-card ${session.tenant.plan === p.id ? "active" : ""}`}>
                <h3>{p.name}</h3>
                {/* 月額料金表示 */}
                <p className="plan-price">${p.price_monthly_usd}/月</p>
                {/* API 日次利用上限を 3 桁区切りで表示 */}
                <p className="hint">API {p.daily_api_limit.toLocaleString()} 回/日</p>
                {/* プランに含まれる主要機能フラグを条件付きリスト表示 */}
                <ul className="headline-list">
                  {p.features.ai && <li>AI分析</li>}
                  {p.features.ai_pro && <li>AI Pro</li>}
                  {p.features.oanda_orders && <li>OANDA注文</li>}
                  {p.features.autotrade && <li>自動取引</li>}
                </ul>
                {/* 現在契約中のプランは変更ボタン不要のため非表示 */}
                {session.tenant.plan !== p.id && (
                  <button type="button" className="btn-secondary" onClick={() => handleUpgrade(p.id)}>
                    {/* ボタンラベル: Stripe 有効かつ有料プラン → "Stripeで申込" / それ以外 → "選択" */}
                    {stripeEnabled && p.id !== "free" ? "Stripeで申込" : "選択"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* OANDA 口座設定カード */}
      <div className="card">
        <h2>OANDA 口座（テナント別）</h2>
        <p className="hint">
          組織ごとに OANDA API トークンと口座 ID を設定。自動取引の mode が live/practice のときに使用されます。
        </p>
        {/* 現在の接続状態サマリー（接続済みの場合のみ表示） */}
        {oandaSummary && <p className="hint">接続状態: {oandaSummary}</p>}
        {/* OANDA 設定入力フォーム */}
        <div className="form-grid">
          {/* 口座 ID 入力: OANDA のサブアカウント番号形式（例: 101-001-XXXXXXX-001） */}
          <label>
            口座 ID
            <input value={oandaAccountId} onChange={(e) => setOandaAccountId(e.target.value)} placeholder="101-001-..." />
          </label>
          {/* API トークン入力: password タイプで表示を隠す。保存済みの場合は空欄のまま保存すると上書きしない */}
          <label>
            API トークン
            <input
              type="password"
              value={oandaToken}
              onChange={(e) => setOandaToken(e.target.value)}
              placeholder="新規入力時のみ（保存済みはマスク表示）"
            />
          </label>
          {/* 接続環境選択: practice（デモ口座）と live（本番口座）を切り替え */}
          <label>
            環境
            <select value={oandaEnv} onChange={(e) => setOandaEnv(e.target.value as "practice" | "live")}>
              <option value="practice">practice（デモ）</option>
              <option value="live">live（本番）</option>
            </select>
          </label>
        </div>
        {/* OANDA 設定保存ボタン */}
        <div className="order-controls">
          <button type="button" className="btn" onClick={handleSaveOanda}>
            OANDA 設定を保存
          </button>
        </div>
      </div>

      {/* API キー管理カード */}
      <div className="card">
        <h2>API キー</h2>
        <p className="hint">
          TradingView Webhook や外部連携に使用。リクエストヘッダー{" "}
          <code>X-API-Key: fx_...</code>
        </p>
        {/* API キー新規発行フォーム */}
        <div className="order-controls">
          {/* キー名入力: 発行目的や用途を識別するための名称 */}
          <label>
            キー名
            <input value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} />
          </label>
          {/* キー発行ボタン: handleCreateKey を呼び出して新しいキーを生成 */}
          <button type="button" className="btn" onClick={handleCreateKey}>
            キーを発行
          </button>
        </div>
        {/* 新規発行キーの表示: キーは発行直後のみ表示（データベースにはハッシュのみ保存） */}
        {createdKey && (
          <div className="api-key-reveal">
            <p>
              <strong>新しい API キー（再表示不可）:</strong>
            </p>
            {/* 完全なキー文字列をコードブロックで表示 */}
            <code>{createdKey}</code>
            {/* ブラウザのローカルストレージにキーを保存するボタン */}
            <button type="button" className="btn-secondary" onClick={() => setApiKey(createdKey)}>
              このブラウザに保存
            </button>
          </div>
        )}
        {/* 発行済み API キー一覧テーブル: 完全なキー文字列は非表示でプレフィックスのみ表示 */}
        <table className="data-table">
          <thead>
            <tr>
              <th>名前</th>
              <th>プレフィックス</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                {/* セキュリティのため完全なキー文字列は表示せずプレフィックスのみ表示 */}
                <td>{k.key_prefix}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
