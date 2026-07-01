/**
 * @file OandaPanel.tsx
 * @description OANDA ブローカー注文パネル
 *
 * OANDA API を通じた成行注文の送信・残高表示・注文履歴一覧を提供する。
 * ペーパートレード（デモ）モードと本番モードの切り替えに対応しており、
 * status.configured が false の場合はペーパーモードとして動作する。
 * 自動取引ページやダッシュボードに組み込まれる注文操作パネル。
 */

"use client";

import { useState } from "react";
import { placeOandaOrder } from "@/lib/api";
import type { BrokerOrder, OandaStatus } from "@/types";

/**
 * OandaPanel のプロパティ型定義。
 * @property status      - OANDA 接続状態（残高・モード・エラーメッセージなど）
 * @property orders      - 取得済みの注文履歴リスト
 * @property symbol      - 注文対象の通貨ペアシンボル（例: "USDJPY"）
 * @property onOrderPlaced - 注文成功後に呼び出すコールバック（親で履歴を再取得するなど）
 */
interface OandaPanelProps {
  /** OANDA の接続設定状態・残高・モード情報 */
  status: OandaStatus;
  /** 表示する注文履歴の配列 */
  orders: BrokerOrder[];
  /** 注文を出す通貨ペア（例: "USDJPY"）*/
  symbol: string;
  /** 注文完了後に親コンポーネントに通知するコールバック */
  onOrderPlaced: () => void;
}

/**
 * OandaPanel
 *
 * OANDA ブローカーへの成行注文送信フォームと注文履歴テーブルを表示する。
 *
 * ### フォームバリデーション・送信処理
 * - `units` の入力範囲は 1〜1,000,000 に制限（HTML の min/max 属性で制御）
 * - 送信中（`submitting === true`）はボタンを disabled にして二重送信を防止
 * - 送信エラーは `error` state に格納してインラインで表示
 *
 * ### 注文フロー
 * 1. ユーザーが「買い」または「売り」ボタンをクリック
 * 2. `submit(side)` が呼ばれ、submitting フラグを立てて API リクエスト送信
 * 3. 成功時: `lastOrder` に結果を保存し、`onOrderPlaced()` で親に通知
 * 4. 失敗時: エラーメッセージを `error` state にセットして表示
 * 5. finally: 成否に関わらず `submitting` を false に戻してボタンを再活性化
 *
 * @param props - {@link OandaPanelProps}
 */
export default function OandaPanel({ status, orders, symbol, onOrderPlaced }: OandaPanelProps) {
  /**
   * 注文数量（units）の入力値。
   * 初期値 1000: FX の標準的なマイクロロット相当の単位数
   */
  const [units, setUnits] = useState(1000);

  /**
   * 注文送信中フラグ。
   * true の間はボタンを無効化して二重送信を防ぐ。
   * 初期値 false
   */
  const [submitting, setSubmitting] = useState(false);

  /**
   * エラーメッセージ。
   * 注文成功時や新しい注文開始時に null にリセットされる。
   * 初期値 null: エラーなし
   */
  const [error, setError] = useState<string | null>(null);

  /**
   * 直近の注文結果。
   * 注文成功後にフォーム下部へ直近の約定情報をサマリー表示するために使用。
   * 初期値 null: 未注文
   */
  const [lastOrder, setLastOrder] = useState<BrokerOrder | null>(null);

  /**
   * 注文送信処理。
   * 指定した売買方向（buy / sell）で `units` 分の成行注文を OANDA API に送信する。
   *
   * @param side - 注文方向: "buy"（買い）または "sell"（売り）
   */
  const submit = async (side: "buy" | "sell") => {
    // 送信開始: ボタンを無効化し、前回のエラーをクリア
    setSubmitting(true);
    setError(null);
    try {
      // OANDA API 経由で成行注文を発注
      const order = await placeOandaOrder(symbol, side, units);
      // 注文成功: 直近注文として保存し、親コンポーネントに通知（履歴再取得など）
      setLastOrder(order);
      onOrderPlaced();
    } catch (e) {
      // 注文失敗: Error オブジェクトのメッセージを表示。それ以外は汎用メッセージ
      setError(e instanceof Error ? e.message : "注文に失敗しました");
    } finally {
      // 成否に関わらず送信フラグを解除してボタンを再活性化
      setSubmitting(false);
    }
  };

  return (
    <div className="card">
      <h2>OANDA 注文</h2>

      {/* 口座ステータスグリッド: モード・残高・含み損益を並べて表示 */}
      <div className="stat-grid" style={{ marginBottom: "1rem" }}>
        <div className="stat-item">
          <div className="label">モード</div>
          {/*
           * status.configured が false の場合はペーパートレードモードと表示。
           * configured が true なら status.mode（"live" / "practice"）を表示。
           */}
          <div className="value">{status.configured ? status.mode : "ペーパー"}</div>
        </div>
        <div className="stat-item">
          <div className="label">残高</div>
          {/* 残高は toLocaleString() で桁区切りを付けて読みやすく表示 */}
          <div className="value">
            {status.balance.toLocaleString()} {status.currency}
          </div>
        </div>
        {/* unrealized_pl（含み損益）が存在する場合のみ表示 */}
        {status.unrealized_pl !== undefined && (
          <div className="stat-item">
            <div className="label">含み損益</div>
            {/* toFixed(2) で小数点2桁まで表示 */}
            <div className="value">{status.unrealized_pl.toFixed(2)}</div>
          </div>
        )}
      </div>

      {/* OANDA 未設定時のヒントメッセージ（APIキー未設定など） */}
      {!status.configured && status.message && (
        <p className="hint">{status.message}</p>
      )}

      {/* 注文フォーム: 数量入力と買い/売りボタン */}
      <div className="order-controls">
        <label>
          数量（units）
          {/*
           * units 入力フィールド。
           * min=1 / max=1000000 でブラウザレベルのバリデーションを実施。
           * onChange で Number 変換してステートを更新。
           */}
          <input
            type="number"
            min={1}
            max={1000000}
            value={units}
            onChange={(e) => setUnits(Number(e.target.value))}
          />
        </label>
        {/* 買い注文ボタン: 送信中は disabled で二重送信防止 */}
        <button
          type="button"
          className="btn-buy"
          disabled={submitting}
          onClick={() => submit("buy")}
        >
          買い
        </button>
        {/* 売り注文ボタン: 送信中は disabled で二重送信防止 */}
        <button
          type="button"
          className="btn-sell"
          disabled={submitting}
          onClick={() => submit("sell")}
        >
          売り
        </button>
      </div>

      {/* エラーメッセージ: 注文失敗時のみ表示 */}
      {error && <p className="error-text">{error}</p>}

      {/* 直近注文サマリー: 成功した直近注文の概要を表示 */}
      {lastOrder && (
        <p className="hint">
          直近注文: {lastOrder.side} {lastOrder.units} @ {lastOrder.fill_price ?? "—"} (
          {lastOrder.broker})
        </p>
      )}

      {/* 注文履歴テーブル */}
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
                {/* created_at を日本語ロケールで日時表示。未設定の場合はダッシュ */}
                <td>{o.created_at ? new Date(o.created_at).toLocaleString("ja-JP") : "—"}</td>
                <td>{o.symbol}</td>
                {/* 買い/売りで文字色を切り替え（CSS クラス text-buy / text-sell） */}
                <td className={o.side === "buy" ? "text-buy" : "text-sell"}>{o.side}</td>
                <td>{o.units}</td>
                {/* 約定価格: 未約定の場合はダッシュ表示 */}
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
