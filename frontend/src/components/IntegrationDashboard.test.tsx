/**
 * @file IntegrationDashboard.test.tsx
 * @description `IntegrationDashboard`（統合トレードダッシュボード）のユニットテスト。
 *
 * 子コンポーネント（TradingView・シグナル・MTF・OANDA）はスタブ化し、
 * ダッシュボード自身の取得・集約・表示分岐を検証する。
 *
 * 検証範囲:
 * - 初期ロードと更新ボタン、シンボル変更による再取得
 * - 読み込み中・エラー時の分岐
 * - 技術スタックの注記
 * - TradingView Webhook シグナル（0 件時の案内・行の描画・方向クラス）
 * - ニュース分析（ML / OpenAI・OpenAI 未設定時の案内・エラー）
 * - Backtrader 結果（成功 / 失敗）と簡易バックテストの要約
 * - OandaPanel への props と、発注後の再読み込み
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import IntegrationDashboard from "./IntegrationDashboard";
import * as api from "@/lib/api";
import * as fixtures from "@/test/fixtures";
import type { DashboardData } from "@/types";

vi.mock("@/components/TradingViewWidget", () => ({
  default: ({ symbol }: { symbol: string }) => <div data-testid="tv" data-symbol={symbol} />,
}));
vi.mock("@/components/SignalPanel", () => ({
  default: ({ symbol, price }: { symbol: string; price: number }) => (
    <div data-testid="signal-panel" data-symbol={symbol} data-price={price} />
  ),
}));
vi.mock("@/components/MultiTimeframePanel", () => ({
  default: ({ symbol }: { symbol: string }) => <div data-testid="mtf" data-symbol={symbol} />,
}));
vi.mock("@/components/OandaPanel", () => ({
  default: ({
    symbol,
    orders,
    onOrderPlaced,
  }: {
    symbol: string;
    orders: unknown[];
    onOrderPlaced: () => void;
  }) => (
    <div data-testid="oanda" data-symbol={symbol} data-orders={orders.length}>
      <button type="button" onClick={onOrderPlaced}>
        発注完了を通知
      </button>
    </div>
  ),
}));

/** API を正常系でモックする */
function mockApis(dashboard?: Partial<DashboardData>) {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getDashboard").mockResolvedValue(fixtures.dashboardData(dashboard));
  vi.spyOn(api, "getNewsAnalysis").mockResolvedValue(fixtures.newsAnalysis());
}

/** 読み込み完了を待つ */
async function waitLoaded() {
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "統合トレードダッシュボード" })).toBeTruthy(),
  );
}

describe("IntegrationDashboard — ロード", () => {
  it("読み込み中は専用メッセージのみ表示する", () => {
    mockApis();
    vi.spyOn(api, "getDashboard").mockReturnValue(new Promise(() => {}));

    render(<IntegrationDashboard />);

    expect(screen.getByText("統合ダッシュボードを読み込み中...")).toBeTruthy();
  });

  it("ダッシュボードとニュースを並列取得する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(api.getDashboard).toHaveBeenCalledWith("USDJPY");
    expect(api.getNewsAnalysis).toHaveBeenCalledWith("USDJPY");
  });

  it("取得に失敗した場合はエラーのみ表示する", async () => {
    mockApis();
    vi.spyOn(api, "getDashboard").mockRejectedValue(new Error("読み込みに失敗しました"));

    render(<IntegrationDashboard />);

    await waitFor(() => expect(screen.getByText("読み込みに失敗しました")).toBeTruthy());
    expect(screen.queryByRole("heading", { name: "統合トレードダッシュボード" })).toBeNull();
  });

  it("更新ボタンで再取得する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "更新" }));

    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledTimes(2));
  });

  it("シンボル変更で再取得する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    fireEvent.change(document.querySelector("select")!, { target: { value: "EURUSD" } });

    await waitFor(() => expect(api.getDashboard).toHaveBeenLastCalledWith("EURUSD"));
  });

  it("技術スタックの注記を表示する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("FastAPI + Next.js — 同一オリジンプロキシ")).toBeTruthy();
  });
});

describe("IntegrationDashboard — TradingView Webhook シグナル", () => {
  it("受信シグナルをテーブルに表示する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("RSI+MACD")).toBeTruthy();
    expect(screen.getByText("151.4")).toBeTruthy();
  });

  it("0 件のときは Webhook の設定案内を表示する", async () => {
    mockApis({ tradingview_signals: [] });
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText(/受信シグナルなし/)).toBeTruthy();
    expect(screen.getByText("/api/tradingview/webhook")).toBeTruthy();
  });

  it("方向に応じて text-buy / text-sell クラスを付ける", async () => {
    mockApis({
      tradingview_signals: [
        { id: 1, action: "buy", price: 151.4, strategy: "A", received_at: "2026-01-02T01:00:00Z" },
        { id: 2, action: "sell", price: 151.1, strategy: "B", received_at: null },
      ] as DashboardData["tradingview_signals"],
    });

    const { container } = render(<IntegrationDashboard />);
    await waitLoaded();

    expect(container.querySelectorAll("td.text-buy")).toHaveLength(1);
    expect(container.querySelectorAll("td.text-sell")).toHaveLength(1);
  });
});

describe("IntegrationDashboard — ニュース分析", () => {
  it("ML と OpenAI のセンチメントを日本語で表示する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("強気")).toBeTruthy();
    expect(screen.getByText("中立")).toBeTruthy();
    expect(screen.getByText("ML 判定は強気です。")).toBeTruthy();
    expect(screen.getByText("OpenAI は中立と判断しました。")).toBeTruthy();
  });

  it("OpenAI 結果が無い場合はその欄を出さない", async () => {
    mockApis();
    vi.spyOn(api, "getNewsAnalysis").mockResolvedValue(
      fixtures.newsAnalysis({ openai: undefined }),
    );

    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.queryByText("OpenAI")).toBeNull();
  });

  it("OpenAI エラーがある場合はメッセージを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getNewsAnalysis").mockResolvedValue(
      fixtures.newsAnalysis({ openai_error: "rate limit" }),
    );

    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("OpenAI: rate limit")).toBeTruthy();
  });

  it("OPENAI_API_KEY 未設定の場合は案内を表示する", async () => {
    mockApis({ openai_configured: false });

    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText(/OPENAI_API_KEY 未設定/)).toBeTruthy();
  });

  it("ヘッドラインは先頭 5 件までに絞る", async () => {
    mockApis();
    vi.spyOn(api, "getNewsAnalysis").mockResolvedValue(
      fixtures.newsAnalysis({
        articles: Array.from({ length: 8 }, (_, i) => ({
          title: `記事 ${i + 1}`,
          url: `https://example.com/${i + 1}`,
        })),
      }),
    );

    const { container } = render(<IntegrationDashboard />);
    await waitLoaded();

    expect(container.querySelectorAll(".headline-list li")).toHaveLength(5);
    expect(screen.queryByText("記事 6")).toBeNull();
  });
});

describe("IntegrationDashboard — バックテスト", () => {
  it("Backtrader 成功時は戦略・資金・リターンを表示する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("RsiMacd")).toBeTruthy();
    expect(screen.getByText("10,000")).toBeTruthy();
    expect(screen.getByText("10,850")).toBeTruthy();
    expect(screen.getByText("8.5%")).toBeTruthy();
  });

  it("Backtrader 失敗時はメッセージを表示する", async () => {
    mockApis({
      backtest_backtrader: {
        status: "error",
        message: "backtrader 未インストール",
      } as DashboardData["backtest_backtrader"],
    });

    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText("backtrader 未インストール")).toBeTruthy();
  });

  it("簡易バックテストの要約とデータソースラベルを表示する", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByText(/勝率 58.3% \/ 取引 24 回 \/ 平均 0.42%（PostgreSQL）/)).toBeTruthy();
  });
});

describe("IntegrationDashboard — 子コンポーネント連携", () => {
  it("各パネルに現在のシンボルを渡す", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    expect(screen.getByTestId("tv").getAttribute("data-symbol")).toBe("USDJPY");
    expect(screen.getByTestId("mtf").getAttribute("data-symbol")).toBe("USDJPY");
    expect(screen.getByTestId("signal-panel").getAttribute("data-price")).toBe("151.5");
    expect(screen.getByTestId("oanda").getAttribute("data-orders")).toBe("1");
  });

  it("OANDA 発注後にダッシュボードを再読み込みする", async () => {
    mockApis();
    render(<IntegrationDashboard />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "発注完了を通知" }));

    await waitFor(() => expect(api.getDashboard).toHaveBeenCalledTimes(2));
  });
});
