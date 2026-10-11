/**
 * @file TradingViewWidget.test.tsx
 * @description `TradingViewWidget`（TradingView チャート埋め込み）のユニットテスト。
 *
 * 外部スクリプト（tv.js）を読み込むため、DOM への副作用を直接検証する。
 *
 * 検証範囲:
 * - 初回マウント時に tv.js を非同期スクリプトとして 1 度だけ追加すること
 * - スクリプト onload で widget() が呼ばれ、想定のオプションが渡ること
 * - TradingView が既にロード済みならスクリプトを追加せず即座にマウントすること
 * - シンボルの OANDA 形式への変換（既知マッピングと未知シンボルのフォールバック）
 * - symbol 変更時のコンテナ初期化と再マウント
 * - 静的な説明テキストの描画
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import TradingViewWidget from "./TradingViewWidget";

/** window.TradingView.widget のモックを設置する */
function installTradingView() {
  const widget = vi.fn();
  (window as unknown as { TradingView?: unknown }).TradingView = { widget };
  return widget;
}

/** DOM に追加された tv.js の <script> を取得する */
function tvScripts(): HTMLScriptElement[] {
  return Array.from(
    document.querySelectorAll<HTMLScriptElement>('script[src="https://s3.tradingview.com/tv.js"]'),
  );
}

afterEach(() => {
  delete (window as unknown as { TradingView?: unknown }).TradingView;
  for (const s of tvScripts()) s.remove();
});

describe("TradingViewWidget — スクリプト読み込み", () => {
  it("未ロードなら tv.js を非同期スクリプトとして追加する", () => {
    render(<TradingViewWidget symbol="USDJPY" />);

    expect(tvScripts()).toHaveLength(1);
    expect(tvScripts()[0].async).toBe(true);
  });

  it("onload で TradingView.widget を呼び出す", () => {
    render(<TradingViewWidget symbol="USDJPY" />);
    const widget = installTradingView();

    tvScripts()[0].onload?.(new Event("load"));

    expect(widget).toHaveBeenCalledTimes(1);
  });

  it("onload 時点でも TradingView が無ければ何もしない", () => {
    render(<TradingViewWidget symbol="USDJPY" />);
    expect(() => tvScripts()[0].onload?.(new Event("load"))).not.toThrow();
  });

  it("ロード済みならスクリプトを追加せず即座に widget を呼ぶ", () => {
    const widget = installTradingView();

    render(<TradingViewWidget symbol="USDJPY" />);

    expect(widget).toHaveBeenCalledTimes(1);
    expect(tvScripts()).toHaveLength(0);
  });
});

describe("TradingViewWidget — widget のオプション", () => {
  it("既知シンボルを OANDA 形式に変換し、日本語・東京時間・4時間足で初期化する", () => {
    const widget = installTradingView();

    render(<TradingViewWidget symbol="USDJPY" />);

    expect(widget).toHaveBeenCalledWith(
      expect.objectContaining({
        symbol: "OANDA:USDJPY",
        interval: "240",
        timezone: "Asia/Tokyo",
        theme: "dark",
        locale: "ja",
        autosize: true,
        enable_publishing: false,
        container_id: "tv_USDJPY",
      }),
    );
  });

  it("未知シンボルも OANDA: プレフィックスを付けてフォールバックする", () => {
    const widget = installTradingView();

    render(<TradingViewWidget symbol="NZDCAD" />);

    expect(widget).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "OANDA:NZDCAD", container_id: "tv_NZDCAD" }),
    );
  });

  it("コンテナ要素にシンボル固有の id を設定する", () => {
    installTradingView();

    const { container } = render(<TradingViewWidget symbol="EURUSD" />);

    expect(container.querySelector(".tv-widget")?.id).toBe("tv_EURUSD");
  });
});

describe("TradingViewWidget — symbol 変更", () => {
  it("symbol が変わるとコンテナを初期化して再マウントする", () => {
    const widget = installTradingView();
    const { rerender, container } = render(<TradingViewWidget symbol="USDJPY" />);

    // 前回のウィジェットが残っている状況を再現する
    const el = container.querySelector(".tv-widget") as HTMLElement;
    el.innerHTML = "<span>古いウィジェット</span>";

    rerender(<TradingViewWidget symbol="EURUSD" />);

    expect(el.innerHTML).toBe("");
    expect(el.id).toBe("tv_EURUSD");
    expect(widget).toHaveBeenCalledTimes(2);
    expect(widget.mock.calls[1][0]).toMatchObject({ symbol: "OANDA:EURUSD" });
  });
});

describe("TradingViewWidget — 静的な説明", () => {
  it("見出しと Pine Script の案内を表示する", () => {
    installTradingView();

    render(<TradingViewWidget symbol="USDJPY" />);

    expect(screen.getByRole("heading", { name: "TradingView チャート" })).toBeTruthy();
    expect(screen.getByText("backend/pine/fx_webhook_strategy.pine")).toBeTruthy();
  });
});
