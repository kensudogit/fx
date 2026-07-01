/**
 * @file PositionSizePanel.tsx
 * @description ポジションサイズ計算パネル
 *
 * 「固定リスク%法」に基づくポジションサイズ計算フォームと結果表示。
 * 口座残高・許容リスク%・ストップ幅（pips）を入力すると、
 * ATR ベースのストップ距離を用いて推奨ロット数・最大損失額・
 * 利確目安 pips をリアルタイムに算出する。
 *
 * テクニカルダッシュボードの補助ツールカードとして表示される。
 *
 * ### 固定リスク%法の計算概要
 * ```
 * ストップ幅 (pips) = 指定値 または ATR ベースの自動算出値
 * 最大許容損失 (USD) = 口座残高 × (リスク% / 100)
 * 推奨ロット = 最大許容損失 / (ストップ幅 × pip値)
 * ```
 */

"use client";

import { useEffect, useState } from "react";
import { getPositionSize } from "@/lib/api";
import type { PositionSizeResult } from "@/types";

/**
 * PositionSizePanel のプロパティ型定義。
 * @property symbol - 計算対象の通貨ペアシンボル（例: "USDJPY"）
 * @property price  - 現在の市場価格（表示専用・読み取り専用フィールドに使用）
 * @property days   - ATR 計算に使用する履歴日数
 */
type Props = {
  /** 通貨ペアシンボル（例: "USDJPY"）*/
  symbol: string;
  /** 現在価格（読み取り専用フィールドに表示）*/
  price: number;
  /** ATR 算出に使う過去データ日数 */
  days: number;
};

/**
 * PositionSizePanel
 *
 * ユーザーが入力した口座残高・リスク%・ストップ pips に基づいて
 * バックエンド API を呼び出し、推奨ロット数・最大損失・利確目安を表示する。
 *
 * ### リアルタイム再計算
 * 入力値（balance, risk, stopPips, symbol, days）が変わるたびに
 * useEffect 内で API が再呼び出しされ、結果を即座に反映する。
 *
 * @param props - {@link Props}
 */
export default function PositionSizePanel({ symbol, price, days }: Props) {
  /**
   * 口座残高（USD）。
   * 初期値 10000: 一般的な FX 入門資金規模のデフォルト値
   */
  const [balance, setBalance] = useState(10000);

  /**
   * リスク許容率（%）。
   * 初期値 1: 固定リスク%法で一般的に推奨される 1% ルール
   * 範囲: 0.1〜10（UI の入力制限による）
   */
  const [risk, setRisk] = useState(1);

  /**
   * ストップロス幅（pips）の手動入力値。
   * 空文字列の場合は ATR ベースの自動算出を使用する。
   * 初期値 "": ATR 自動計算がデフォルト
   */
  const [stopPips, setStopPips] = useState("");

  /**
   * バックエンド API から取得したポジションサイズ計算結果。
   * 初期値 null: 未取得または取得失敗
   */
  const [result, setResult] = useState<PositionSizeResult | null>(null);

  /**
   * API 通信中フラグ。
   * true の間は「計算中...」メッセージを表示してユーザーに待機を促す。
   * 初期値 false
   */
  const [loading, setLoading] = useState(false);

  /**
   * 入力値変更時にポジションサイズを再計算する副作用。
   *
   * ### 計算ロジック
   * 1. stopPips が空文字の場合は opts に stopPips を含めず、
   *    バックエンドで ATR ベースのストップ幅を自動算出させる
   * 2. stopPips が入力されている場合は数値変換して opts に追加し、
   *    手動ストップ幅での計算を実施
   *
   * 依存配列: [symbol, balance, risk, stopPips, days]
   * — これら全ての値が変わるたびに再計算が走る
   */
  useEffect(() => {
    setLoading(true);
    // API リクエストのパラメータオブジェクト（stopPips は条件付きで追加）
    const opts: { accountBalance: number; riskPercent: number; stopPips?: number; days: number } = {
      accountBalance: balance,
      riskPercent: risk,
      days,
    };
    // stopPips が空でない場合のみオプションに追加（空 = ATR 自動算出を使用）
    if (stopPips) opts.stopPips = Number(stopPips);
    getPositionSize(symbol, opts)
      .then(setResult)
      .catch(() => setResult(null))  // 取得失敗時は結果を非表示にする
      .finally(() => setLoading(false));
  }, [symbol, balance, risk, stopPips, days]);

  return (
    <div className="card trader-tool-card">
      <h2>ポジションサイズ計算</h2>
      {/* 計算方法の説明ヒント: ATR ベースのストップ幅を用いた固定リスク%法 */}
      <p className="tool-hint">ATR ベースのストップ幅から推奨ロットを算出（口座リスク%管理）</p>

      {/* 入力フォーム: 2カラムグリッドレイアウト */}
      <div className="tool-form grid-2">
        <div className="form-group">
          <label>口座残高 (USD)</label>
          {/* min=100 で最低残高を制限（ゼロ除算防止） */}
          <input type="number" value={balance} onChange={(e) => setBalance(Number(e.target.value))} min={100} />
        </div>
        <div className="form-group">
          <label>リスク (%)</label>
          {/*
           * リスク率入力: 0.1〜10% の範囲、0.1% 刻み。
           * 10% 以上は過大リスクとなるため上限設定。
           */}
          <input type="number" value={risk} onChange={(e) => setRisk(Number(e.target.value))} min={0.1} max={10} step={0.1} />
        </div>
        <div className="form-group">
          <label>ストップ (pips) — 空欄でATR</label>
          {/*
           * ストップ幅の手動指定フィールド。
           * 空欄の場合はバックエンドが ATR（平均真幅）を使って自動算出する。
           * placeholder="自動" でデフォルト動作をユーザーに示す。
           */}
          <input type="number" value={stopPips} onChange={(e) => setStopPips(e.target.value)} placeholder="自動" />
        </div>
        <div className="form-group">
          <label>現在価格</label>
          {/* 現在価格は表示専用（親コンポーネントから受け取る）*/}
          <input type="text" value={price} readOnly />
        </div>
      </div>

      {/* ローディング中の表示 */}
      {loading && <p className="tool-hint">計算中...</p>}

      {/* 計算結果の表示（ローディング中は非表示） */}
      {result && !loading && (
        <div className="stat-grid" style={{ marginTop: "0.75rem" }}>
          <div className="stat-item">
            <div className="label">推奨ロット</div>
            {/* ハイライトクラスで強調表示: 最も重要な計算結果 */}
            <div className="value highlight">{result.recommended_lots}</div>
          </div>
          <div className="stat-item">
            <div className="label">ストップ</div>
            {/*
             * ストップ幅（pips）の表示。
             * atr_based_stop が true の場合は "(ATR)" を付記して自動算出であることを示す。
             */}
            <div className="value">{result.stop_pips} pips{result.atr_based_stop ? " (ATR)" : ""}</div>
          </div>
          <div className="stat-item">
            <div className="label">最大損失</div>
            {/* 最大損失は赤色（--sell カラー変数）で警告的に表示 */}
            <div className="value" style={{ color: "var(--sell)" }}>${result.max_loss_usd}</div>
          </div>
          <div className="stat-item">
            <div className="label">利確目安</div>
            {/* 利確目安は緑色（--buy カラー変数）でポジティブに表示 */}
            <div className="value" style={{ color: "var(--buy)" }}>{result.suggested_take_profit_pips} pips</div>
          </div>
        </div>
      )}
    </div>
  );
}
