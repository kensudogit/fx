/**
 * @file TradingViewWidget.tsx
 * @description TradingView チャートウィジェット埋め込みコンポーネント
 *
 * TradingView の公式ウィジェットライブラリ（tv.js）を動的にロードし、
 * 指定した通貨ペアの 4 時間足チャートをページ内に埋め込む。
 *
 * ### TradingView Webhook ウィジェット埋め込みの仕組み
 * 1. コンポーネントがマウントされると useEffect 内で DOM 要素を準備
 * 2. `window.TradingView` が既にロード済みの場合は即座にウィジェットを初期化
 * 3. 未ロードの場合は `<script src="https://s3.tradingview.com/tv.js">` を
 *    動的に document.body に追加し、onload コールバックで初期化する
 * 4. symbol が変わると useEffect が再実行され、コンテナを空にしてから
 *    新しいシンボルのウィジェットを再初期化する
 *
 * ### Pine Script Webhook 連携
 * TradingView 上で作成した Pine Script ストラテジー（fx_webhook_strategy.pine）の
 * アラートを本バックエンドの Webhook エンドポイントに送信することで、
 * シグナルが自動記録・自動注文トリガーとして機能する。
 */

"use client";

import { useEffect, useRef } from "react";

/**
 * 通貨ペアシンボル → TradingView のシンボル文字列マッピング。
 * OANDA のシンボル形式に変換してウィジェットに渡す。
 * マッピングに存在しないシンボルは `OANDA:${symbol}` にフォールバックする。
 */
const TV_SYMBOL: Record<string, string> = {
  USDJPY: "OANDA:USDJPY",
  EURUSD: "OANDA:EURUSD",
  GBPUSD: "OANDA:GBPUSD",
  AUDUSD: "OANDA:AUDUSD",
};

/**
 * TradingViewWidget のプロパティ型定義。
 * @property symbol - 表示する通貨ペアのシンボル（例: "USDJPY"）
 */
interface TradingViewWidgetProps {
  /** 表示する通貨ペア（TV_SYMBOL マッピングに対応した文字列）*/
  symbol: string;
}

/**
 * TradingViewWidget
 *
 * TradingView ウィジェットを React の ref でマウントされた DOM 要素に埋め込む。
 * 外部スクリプト（tv.js）を動的にロードするため SSR 非対応のクライアント専用コンポーネント。
 *
 * ### ウィジェット設定
 * - interval: "240" → 4 時間足チャート
 * - timezone: "Asia/Tokyo" → 東京時間表示
 * - theme: "dark" → ダークテーマ
 * - locale: "ja" → 日本語 UI
 * - enable_publishing: false → チャート共有機能を無効化
 *
 * @param props - {@link TradingViewWidgetProps}
 */
export default function TradingViewWidget({ symbol }: TradingViewWidgetProps) {
  /**
   * ウィジェットをマウントする DOM 要素への参照。
   * useRef により再レンダリング時も同じ DOM ノードを参照し続ける。
   */
  const containerRef = useRef<HTMLDivElement>(null);

  /**
   * TradingView ウィジェットを初期化する副作用。
   * symbol が変わるたびに既存のウィジェットを破棄し、新しいシンボルで再初期化する。
   *
   * ### 処理フロー
   * 1. containerRef の DOM 要素を取得（null の場合は早期リターン）
   * 2. innerHTML を空文字でリセットして既存ウィジェットを破棄
   * 3. コンテナ要素に一意な ID を設定（`tv_${symbol}`）
   * 4. window.TradingView が存在する場合 → 即座に mount() を呼び出す
   * 5. 存在しない場合 → script タグを動的挿入し、onload で mount() を呼び出す
   *
   * 依存配列: [symbol] — シンボル変更時のみウィジェットを再生成
   */
  useEffect(() => {
    const el = containerRef.current;
    // DOM 要素が存在しない場合はスキップ（SSR やコンポーネントが非表示の場合）
    if (!el) return;

    // 既存のウィジェット HTML を完全にクリアして再初期化に備える
    el.innerHTML = "";

    // ウィジェットコンテナに一意な ID を割り当てる（複数ウィジェット共存時の衝突防止）
    const widgetId = `tv_${symbol}`;
    el.id = widgetId;

    /**
     * TradingView ウィジェットを実際に初期化する内部関数。
     * window.TradingView が利用可能な状態でのみ呼び出される。
     */
    const mount = () => {
      // TypeScript の型安全のために window を unknown 経由でキャスト
      const tv = (window as unknown as { TradingView?: { widget: (o: object) => void } })
        .TradingView;
      // TradingView ライブラリがロードされていない場合は何もしない
      if (!tv) return;
      tv.widget({
        autosize: true,                                      // コンテナに合わせて自動リサイズ
        symbol: TV_SYMBOL[symbol] ?? `OANDA:${symbol}`,    // OANDA シンボル形式に変換
        interval: "240",                                     // 4 時間足（240 分）
        timezone: "Asia/Tokyo",                             // 東京タイムゾーン
        theme: "dark",                                       // ダークテーマ
        style: "1",                                          // ローソク足スタイル
        locale: "ja",                                        // 日本語ロケール
        toolbar_bg: "#1a2332",                              // ツールバー背景色（サイトテーマに合わせた色）
        enable_publishing: false,                           // チャート公開機能を無効化
        container_id: widgetId,                             // マウント先の DOM ID
      });
    };

    /*
     * window.TradingView が既にロード済みかチェック。
     * 同じページで複数のウィジェットを使う場合、2 回目以降は
     * スクリプトが既にロードされているため即座に mount() を実行できる。
     */
    if ((window as unknown as { TradingView?: unknown }).TradingView) {
      mount();
      return;
    }

    /*
     * TradingView スクリプトが未ロードの場合は動的に script タグを挿入。
     * async 属性で非同期ロードし、ページのレンダリングをブロックしない。
     * onload コールバックでウィジェットを初期化する。
     */
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/tv.js";
    script.async = true;
    script.onload = mount;
    document.body.appendChild(script);
  }, [symbol]);  // symbol が変わるたびにウィジェットを再初期化

  return (
    <div className="card tv-widget-card">
      <h2>TradingView チャート</h2>
      {/*
       * Webhook 連携の説明ヒント。
       * Pine Script アラートを Webhook に送信することでシグナルが記録される。
       * 対応する Pine Script ファイルはリポジトリの backend/pine/ に格納。
       */}
      <p className="hint">
        Pine Script アラートを Webhook に送信するとシグナルが記録されます（
        <code>backend/pine/fx_webhook_strategy.pine</code>）
      </p>
      {/* ウィジェットのマウント先 DOM 要素（useEffect 内で id と innerHTML を操作）*/}
      <div ref={containerRef} className="tv-widget" />
    </div>
  );
}
