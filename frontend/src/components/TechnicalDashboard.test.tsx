/**
 * @file TechnicalDashboard.test.tsx
 * @description `TechnicalDashboard`（テクニカル分析ダッシュボード）のユニットテスト。
 *
 * 子コンポーネント（チャート・各パネル）はスタブ化し、
 * このコンポーネント自身が担う「取得・状態遷移・表示分岐」を検証する。
 *
 * 検証範囲:
 * - 初期ロード（シンボル一覧・テクニカル・シグナル・ML 予測の並列取得）
 * - シンボル / 期間の変更による再取得
 * - データ同期ボタン（同期 → 再取得、実行中の非活性化）
 * - チャート画像ボタン（成功・失敗・実行中）
 * - エラーバナー
 * - 指標タブの切り替えと対応するチャートの描画
 * - データソースバッジ（既知ラベル・未知はそのまま）
 * - ライブ価格の反映と LIVE バッジ
 * - ML 予測が success のときだけ予測欄を出すこと
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TechnicalDashboard from "./TechnicalDashboard";
import * as api from "@/lib/api";
import * as livePrices from "@/lib/useLivePrices";
import { mlPrediction, technicalAnalysis, tradingSignal } from "@/test/fixtures";

// 子コンポーネントはスタブ化して、このダッシュボード自身の責務に絞る
vi.mock("@/components/Chart", () => ({
  default: ({ showMA, showBB, showIchimoku }: Record<string, boolean | undefined>) => (
    <div data-testid="price-chart" data-mode={showBB ? "bb" : showIchimoku ? "ichimoku" : showMA ? "ma" : ""} />
  ),
  OscillatorChart: ({ type }: { type: string }) => <div data-testid="oscillator" data-type={type} />,
}));
vi.mock("@/components/SignalPanel", () => ({
  default: ({ symbol, price }: { symbol: string; price: number }) => (
    <div data-testid="signal-panel" data-symbol={symbol} data-price={price} />
  ),
}));
vi.mock("@/components/MultiTimeframePanel", () => ({
  default: ({ symbol }: { symbol: string }) => <div data-testid="mtf" data-symbol={symbol} />,
}));
vi.mock("@/components/PositionSizePanel", () => ({
  default: ({ days }: { days: number }) => <div data-testid="position-size" data-days={days} />,
}));
vi.mock("@/components/BacktestPanel", () => ({
  default: ({ days }: { days: number }) => <div data-testid="backtest" data-days={days} />,
}));
vi.mock("@/components/EventAlertBanner", () => ({
  default: () => <div data-testid="event-alert" />,
}));

/** 正常系の API モックを一括で設置する */
function mockApis(over: { technical?: ReturnType<typeof technicalAnalysis> } = {}) {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getTechnicalAnalysis").mockResolvedValue(over.technical ?? technicalAnalysis());
  vi.spyOn(api, "getTradingSignals").mockResolvedValue({
    symbol: "USDJPY",
    signals: [tradingSignal()],
    price: 151.5,
  });
  vi.spyOn(api, "getMLPrediction").mockResolvedValue(mlPrediction());
  vi.spyOn(livePrices, "useLivePrices").mockReturnValue({ quotes: {}, connected: false });
}

/** 読み込み完了（見出し表示）まで待つ */
async function waitLoaded() {
  await waitFor(() => expect(screen.getByRole("heading", { name: "テクニカル分析" })).toBeTruthy());
}

/** stat-item の label→value マップ */
function stats(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const el of Array.from(document.querySelectorAll(".stat-item"))) {
    out[el.querySelector(".label")?.textContent ?? ""] =
      el.querySelector(".value")?.textContent ?? "";
  }
  return out;
}

describe("TechnicalDashboard — 初期ロード", () => {
  it("読み込み中はローディング表示のみ", () => {
    mockApis();
    vi.spyOn(api, "getTechnicalAnalysis").mockReturnValue(new Promise(() => {}));

    render(<TechnicalDashboard />);

    expect(screen.getByText("データを読み込み中...")).toBeTruthy();
  });

  it("既定のシンボル・期間（USDJPY / 200 日）で取得する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(api.getTechnicalAnalysis).toHaveBeenCalledWith("USDJPY", 200);
    expect(api.getTradingSignals).toHaveBeenCalledWith("USDJPY", 200);
    expect(api.getMLPrediction).toHaveBeenCalledWith("USDJPY", 200);
  });

  it("シンボル一覧をセレクトの選択肢にする", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    const options = Array.from(document.querySelectorAll("select")[0].options).map((o) => o.value);
    expect(options).toEqual(["USDJPY", "EURUSD"]);
  });

  it("イベントアラートバナーと各パネルを描画する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.getByTestId("event-alert")).toBeTruthy();
    expect(screen.getByTestId("mtf").getAttribute("data-symbol")).toBe("USDJPY");
    expect(screen.getByTestId("signal-panel").getAttribute("data-price")).toBe("151.5");
    expect(screen.getByTestId("position-size").getAttribute("data-days")).toBe("200");
    expect(screen.getByTestId("backtest").getAttribute("data-days")).toBe("200");
  });
});

describe("TechnicalDashboard — コントロール", () => {
  it("シンボルを変更すると再取得する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.change(document.querySelectorAll("select")[0], { target: { value: "EURUSD" } });

    await waitFor(() => expect(api.getTechnicalAnalysis).toHaveBeenLastCalledWith("EURUSD", 200));
  });

  it("期間を変更すると再取得する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.change(document.querySelectorAll("select")[1], { target: { value: "90" } });

    await waitFor(() => expect(api.getTechnicalAnalysis).toHaveBeenLastCalledWith("USDJPY", 90));
  });

  it("期間の選択肢は 90 / 200 / 365 日", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    const options = Array.from(document.querySelectorAll("select")[1].options).map(
      (o) => o.textContent,
    );
    expect(options).toEqual(["90日", "200日", "365日"]);
  });
});

describe("TechnicalDashboard — データ同期", () => {
  it("同期してから再取得する", async () => {
    mockApis();
    const sync = vi.spyOn(api, "syncMarketData").mockResolvedValue({
      symbol: "USDJPY",
      rows_synced: 200,
      latest_close: 151.5,
      latest_date: "2026-01-03",
    });
    render(<TechnicalDashboard />);
    await waitLoaded();
    const before = vi.mocked(api.getTechnicalAnalysis).mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "データ同期" }));

    await waitFor(() => expect(sync).toHaveBeenCalledWith("USDJPY", 200));
    await waitFor(() =>
      expect(vi.mocked(api.getTechnicalAnalysis).mock.calls.length).toBe(before + 1),
    );
  });

  it("同期中はボタンを非活性化してラベルを変える", async () => {
    mockApis();
    vi.spyOn(api, "syncMarketData").mockReturnValue(new Promise(() => {}));
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "データ同期" }));

    const btn = screen.getByRole("button", { name: "同期中..." }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("同期に失敗したらエラーバナーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "syncMarketData").mockRejectedValue(new Error("Yahoo Finance 接続失敗"));
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "データ同期" }));

    await waitFor(() => expect(screen.getByText("Yahoo Finance 接続失敗")).toBeTruthy());
  });
});

describe("TechnicalDashboard — チャート画像", () => {
  it("現在のシンボル・期間で画像を開く", async () => {
    mockApis();
    const open = vi.spyOn(api, "openChartImage").mockResolvedValue(undefined);
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "チャート画像" }));

    await waitFor(() => expect(open).toHaveBeenCalledWith("USDJPY", 200));
  });

  it("取得中はラベルを『取得中...』にする", async () => {
    mockApis();
    vi.spyOn(api, "openChartImage").mockReturnValue(new Promise(() => {}));
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "チャート画像" }));

    expect((screen.getByRole("button", { name: "取得中..." }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("失敗時はエラーバナーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "openChartImage").mockRejectedValue(new Error("ポップアップがブロックされました"));
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "チャート画像" }));

    await waitFor(() => expect(screen.getByText("ポップアップがブロックされました")).toBeTruthy());
  });
});

describe("TechnicalDashboard — データソースバッジ", () => {
  it("既知のソースは日本語ラベルに変換する", async () => {
    mockApis({ technical: technicalAnalysis({ source: "yahoo_finance" }) });
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.getByText("データソース: Yahoo Finance")).toBeTruthy();
  });

  it("未知のソースはそのまま表示する", async () => {
    mockApis({ technical: technicalAnalysis({ source: "custom_feed" }) });
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.getByText("データソース: custom_feed")).toBeTruthy();
  });
});

describe("TechnicalDashboard — 指標タブ", () => {
  it("初期表示は価格 + MA タブ", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.getByTestId("price-chart").getAttribute("data-mode")).toBe("ma");
  });

  it.each([
    ["ボリンジャーバンド", "price-chart", "bb"],
    ["一目均衡表", "price-chart", "ichimoku"],
  ])("%s タブで対応するチャートを描画する", async (label, testId, mode) => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: label }));

    expect(screen.getByTestId(testId).getAttribute("data-mode")).toBe(mode);
  });

  it.each([
    ["RSI", "rsi"],
    ["MACD", "macd"],
    ["ストキャスティクス", "stochastic"],
  ])("%s タブではオシレーターチャートを描画する", async (label, type) => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: label }));

    expect(screen.getByTestId("oscillator").getAttribute("data-type")).toBe(type);
    expect(screen.queryByTestId("price-chart")).toBeNull();
  });

  it("選択中のタブに active クラスを付ける", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "RSI" }));

    expect(screen.getByRole("button", { name: "RSI" }).className).toContain("active");
    expect(screen.getByRole("button", { name: "価格 + MA" }).className).not.toContain("active");
  });
});

describe("TechnicalDashboard — サマリー", () => {
  it("終値・RSI・MACD を整形して表示する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(stats()["終値"]).toBe("151.5");
    expect(stats()["RSI (14)"]).toBe("61.7");
    expect(stats()["MACD"]).toBe("0.3456");
  });

  it("RSI / MACD が無い場合はダッシュを表示する", async () => {
    mockApis({
      technical: technicalAnalysis({ latest: { close: 151.5, rsi: null, macd: null } }),
    });
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(stats()["RSI (14)"]).toBe("-");
    expect(stats()["MACD"]).toBe("-");
  });

  it("ML 予測が success のときだけ予測欄を表示する", async () => {
    mockApis();
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(stats()["ML予測価格"]).toBe("152.34");
    expect(stats()["モデル精度 (R²)"]).toBe("0.87");
  });

  it("ML 予測が失敗している場合は予測欄を出さない", async () => {
    mockApis();
    vi.spyOn(api, "getMLPrediction").mockResolvedValue(mlPrediction({ status: "error" }));
    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(stats()["ML予測価格"]).toBeUndefined();
  });
});

describe("TechnicalDashboard — ライブ価格", () => {
  it("ライブ価格があれば終値の代わりに表示し LIVE バッジを出す", async () => {
    mockApis();
    vi.spyOn(livePrices, "useLivePrices").mockReturnValue({
      quotes: { USDJPY: { symbol: "USDJPY", price: 151.93 } },
      connected: true,
    });

    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.getByText("151.93")).toBeTruthy();
    expect(screen.getByText("LIVE")).toBeTruthy();
  });

  it("未接続ならライブ価格を表示しても LIVE バッジは出さない", async () => {
    mockApis();
    vi.spyOn(livePrices, "useLivePrices").mockReturnValue({
      quotes: { USDJPY: { symbol: "USDJPY", price: 151.93 } },
      connected: false,
    });

    render(<TechnicalDashboard />);
    await waitLoaded();

    expect(screen.queryByText("LIVE")).toBeNull();
  });
});

describe("TechnicalDashboard — エラー", () => {
  it("初期取得に失敗した場合はエラーバナーのみ表示する", async () => {
    vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: [] });
    vi.spyOn(api, "getTechnicalAnalysis").mockRejectedValue(new Error("データ取得に失敗しました"));
    vi.spyOn(api, "getTradingSignals").mockRejectedValue(new Error("x"));
    vi.spyOn(api, "getMLPrediction").mockRejectedValue(new Error("x"));
    vi.spyOn(livePrices, "useLivePrices").mockReturnValue({ quotes: {}, connected: false });

    render(<TechnicalDashboard />);

    await waitFor(() => expect(screen.getByText("データ取得に失敗しました")).toBeTruthy());
    expect(screen.queryByTestId("price-chart")).toBeNull();
  });
});
