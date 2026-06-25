"use client";

import { useEffect, useState } from "react";
import {
  createApiKey,
  getBillingPlans,
  listApiKeys,
  upgradePlan,
  type BillingPlan,
} from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { setApiKey } from "@/lib/auth";

export default function SettingsPage() {
  const { session, refresh } = useAuth();
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [keys, setKeys] = useState<{ id: number; name: string; key_prefix: string }[]>([]);
  const [newKeyName, setNewKeyName] = useState("TradingView Webhook");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBillingPlans().then((r) => setPlans(r.plans));
    listApiKeys().then((r) => setKeys(r.keys)).catch(() => {});
  }, []);

  const handleUpgrade = async (plan: string) => {
    setError(null);
    try {
      await upgradePlan(plan);
      setMessage(`${plan} プランに変更しました`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "プラン変更に失敗しました");
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
                  {p.features.analysis_intelligence && <li>統合インテリジェンス</li>}
                </ul>
                {session.tenant.plan !== p.id && (
                  <button type="button" className="btn-secondary" onClick={() => handleUpgrade(p.id)}>
                    選択
                  </button>
                )}
              </div>
            ))}
          </div>
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
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setApiKey(createdKey)}
            >
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
