/**
 * React コンポーネント — OandaPanel
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

"use client";

import { useState } from "react";
import { placeOandaOrder } from "@/lib/api";
import type { BrokerOrder, OandaStatus } from "@/types";

interface OandaPanelProps {
  status: OandaStatus;
  orders: BrokerOrder[];
  symbol: string;
  onOrderPlaced: () => void;
}

export default function OandaPanel({ status, orders, symbol, onOrderPlaced }: OandaPanelProps) {
  const [units, setUnits] = useState(1000);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastOrder, setLastOrder] = useState<BrokerOrder | null>(null);

  const submit = async (side: "buy" | "sell") => {
    setSubmitting(true);
    setError(null);
    try {
      const order = await placeOandaOrder(symbol, side, units);
      setLastOrder(order);
      onOrderPlaced();
    } catch (e) {
      setError(e instanceof Error ? e.message : "注文に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card">
      <h2>OANDA 注文</h2>
      <div className="stat-grid" style={{ marginBottom: "1rem" }}>
        <div className="stat-item">
          <div className="label">モード</div>
          <div className="value">{status.configured ? status.mode : "ペーパー"}</div>
        </div>
        <div className="stat-item">
          <div className="label">残高</div>
          <div className="value">
            {status.balance.toLocaleString()} {status.currency}
          </div>
        </div>
        {status.unrealized_pl !== undefined && (
          <div className="stat-item">
            <div className="label">含み損益</div>
            <div className="value">{status.unrealized_pl.toFixed(2)}</div>
          </div>
        )}
      </div>
      {!status.configured && status.message && (
        <p className="hint">{status.message}</p>
      )}
      <div className="order-controls">
        <label>
          数量（units）
          <input
            type="number"
            min={1}
            max={1000000}
            value={units}
            onChange={(e) => setUnits(Number(e.target.value))}
          />
        </label>
        <button
          type="button"
          className="btn-buy"
          disabled={submitting}
          onClick={() => submit("buy")}
        >
          買い
        </button>
        <button
          type="button"
          className="btn-sell"
          disabled={submitting}
          onClick={() => submit("sell")}
        >
          売り
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {lastOrder && (
        <p className="hint">
          直近注文: {lastOrder.side} {lastOrder.units} @ {lastOrder.fill_price ?? "—"} (
          {lastOrder.broker})
        </p>
      )}
      <h3 style={{ marginTop: "1rem" }}>注文履歴</h3>
      {orders.length === 0 ? (
        <p className="hint">注文履歴はありません</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>時刻</th>
              <th>通貨</th>
              <th>方向</th>
              <th>数量</th>
              <th>約定</th>
              <th>状態</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.created_at ? new Date(o.created_at).toLocaleString("ja-JP") : "—"}</td>
                <td>{o.symbol}</td>
                <td className={o.side === "buy" ? "text-buy" : "text-sell"}>{o.side}</td>
                <td>{o.units}</td>
                <td>{o.fill_price ?? "—"}</td>
                <td>{o.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
