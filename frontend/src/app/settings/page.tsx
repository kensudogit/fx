"use client";

import { useEffect, useState } from "react";
import {
  createApiKey,
  createBillingCheckout,
  getBillingPlans,
  getOandaSettings,
  listApiKeys,
  updateOandaSettings,
  upgradePlan,
  type BillingPlan,
} from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { setApiKey } from "@/lib/auth";

export default function SettingsPage() {
  const { session, refresh } = useAuth();
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [stripeEnabled, setStripeEnabled] = useState(false);
  const [keys, setKeys] = useState<{ id: number; name: string; key_prefix: string }[]>([]);
  const [newKeyName, setNewKeyName] = useState("TradingView Webhook");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [oandaAccountId, setOandaAccountId] = useState("");
  const [oandaToken, setOandaToken] = useState("");
  const [oandaEnv, setOandaEnv] = useState<"practice" | "live">("practice");
  const [oandaSummary, setOandaSummary] = useState<string | null>(null);

  useEffect(() => {
    getBillingPlans().then((r) => {
      setPlans(r.plans);
      setStripeEnabled(Boolean(r.stripe_enabled));
    });
    listApiKeys().then((r) => setKeys(r.keys)).catch(() => {});
    getOandaSettings()
      .then((r) => {
        if (r.settings?.account_id) setOandaAccountId(r.settings.account_id);
        if (r.settings?.environment === "live") setOandaEnv("live");
        if (r.account_summary?.configured) {
          setOandaSummary(
            `${r.account_summary.mode} · $${r.account_summary.balance.toLocaleString()} (${r.account_summary.source})`,
          );
        } else {
          setOandaSummary(r.account_summary?.message ?? null);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("checkout") === "success") {
      setMessage("Stripe 決済が完了しました。プランを反映中...");
      refresh();
    }
  }, [refresh]);

  const handleUpgrade = async (plan: string) => {
    setError(null);
    try {
      if (stripeEnabled && plan !== "free") {
        const { checkout_url } = await createBillingCheckout(plan);
        window.location.href = checkout_url;
        return;
      }
      await upgradePlan(plan);
      setMessage(`${plan} プランに変更しました`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "プラン変更に失敗しました");
    }
  };

  const handleSaveOanda = async () => {
    setError(null);
    try {
      await updateOandaSettings({
        account_id: oandaAccountId,
        api_token: oandaToken || undefined,
        environment: oandaEnv,
      });
      setOandaToken("");
      setMessage("OANDA 設定を保存しました");
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

  const handleCreateKey = async () => {
    setError(null);
    setCreatedKey(null);
    try {
      const res = await createApiKey(newKeyName);
      setCreatedKey(res.api_key);
      setKeys(await listApiKeys().then((r) => r.keys));
    } catch (e) {
      setError(e instanceof Error ? e.message : "APIキー作成に失敗しました");
    }
  };

  if (!session) {
    return <div className="loading">読み込み中...</div>;
  }

  return (
    <>
      <div className="page-header">
        <h1>設定・課金</h1>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>ワークスペース</h2>
          <p>
            <strong>{session.tenant.name}</strong>（{session.tenant.slug}）
          </p>
          <p>
            プラン: <span className="badge badge-neutral">{session.tenant.plan.toUpperCase()}</span>
          </p>
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
          <p className="hint">ログイン: {session.user.email}</p>
        </div>

        <div className="card">
          <h2>プラン</h2>
          {stripeEnabled && <p className="hint">有料プランは Stripe Checkout で決済されます。</p>}
          {message && <p className="hint">{message}</p>}
          {error && <p className="error-text">{error}</p>}
          <div className="plan-grid">
            {plans.map((p) => (
              <div key={p.id} className={`plan-card ${session.tenant.plan === p.id ? "active" : ""}`}>
                <h3>{p.name}</h3>
                <p className="plan-price">${p.price_monthly_usd}/月</p>
                <p className="hint">API {p.daily_api_limit.toLocaleString()} 回/日</p>
                <ul className="headline-list">
                  {p.features.ai && <li>AI分析</li>}
                  {p.features.ai_pro && <li>AI Pro</li>}
                  {p.features.oanda_orders && <li>OANDA注文</li>}
                  {p.features.autotrade && <li>自動取引</li>}
                </ul>
                {session.tenant.plan !== p.id && (
                  <button type="button" className="btn-secondary" onClick={() => handleUpgrade(p.id)}>
                    {stripeEnabled && p.id !== "free" ? "Stripeで申込" : "選択"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h2>OANDA 口座（テナント別）</h2>
        <p className="hint">
          組織ごとに OANDA API トークンと口座 ID を設定。自動取引の mode が live/practice のときに使用されます。
        </p>
        {oandaSummary && <p className="hint">接続状態: {oandaSummary}</p>}
        <div className="form-grid">
          <label>
            口座 ID
            <input value={oandaAccountId} onChange={(e) => setOandaAccountId(e.target.value)} placeholder="101-001-..." />
          </label>
          <label>
            API トークン
            <input
              type="password"
              value={oandaToken}
              onChange={(e) => setOandaToken(e.target.value)}
              placeholder="新規入力時のみ（保存済みはマスク表示）"
            />
          </label>
          <label>
            環境
            <select value={oandaEnv} onChange={(e) => setOandaEnv(e.target.value as "practice" | "live")}>
              <option value="practice">practice（デモ）</option>
              <option value="live">live（本番）</option>
            </select>
          </label>
        </div>
        <div className="order-controls">
          <button type="button" className="btn" onClick={handleSaveOanda}>
            OANDA 設定を保存
          </button>
        </div>
      </div>

      <div className="card">
        <h2>API キー</h2>
        <p className="hint">
          TradingView Webhook や外部連携に使用。リクエストヘッダー{" "}
          <code>X-API-Key: fx_...</code>
        </p>
        <div className="order-controls">
          <label>
            キー名
            <input value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} />
          </label>
          <button type="button" className="btn" onClick={handleCreateKey}>
            キーを発行
          </button>
        </div>
        {createdKey && (
          <div className="api-key-reveal">
            <p>
              <strong>新しい API キー（再表示不可）:</strong>
            </p>
            <code>{createdKey}</code>
            <button type="button" className="btn-secondary" onClick={() => setApiKey(createdKey)}>
              このブラウザに保存
            </button>
          </div>
        )}
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
                <td>{k.key_prefix}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
