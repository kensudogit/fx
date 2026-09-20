/**
 * @file SignalPanel.test.tsx
 * @description `SignalPanel`（トレードシグナル一覧）のユニットテスト。
 *
 * 純粋な表示コンポーネントのため、props から導かれる集計と表示分岐を検証する。
 *
 * 検証範囲:
 * - 買い / 売りシグナルの件数集計
 * - 総合判断（買い優勢 / 売り優勢 / 中立）とバッジのクラス
 * - シグナル 0 件のときの案内表示
 * - 各シグナル行の指標名・方向ラベル・指標値・理由
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import SignalPanel from "./SignalPanel";
import { tradingSignal } from "@/test/fixtures";

describe("SignalPanel — ヘッダーと現在価格", () => {
  it("シンボルを見出しに表示する", () => {
    render(<SignalPanel signals={[]} price={151.5} symbol="USDJPY" />);
    expect(screen.getByRole("heading", { name: /USDJPY/ })).toBeTruthy();
  });

  it("現在価格を表示する", () => {
    render(<SignalPanel signals={[]} price={151.52} symbol="USDJPY" />);
    expect(screen.getByText("151.52")).toBeTruthy();
  });
});

describe("SignalPanel — 総合判断", () => {
  it("買いが多い場合は『買い優勢』", () => {
    const signals = [
      tradingSignal({ indicator: "RSI", signal: "buy" }),
      tradingSignal({ indicator: "MACD", signal: "buy" }),
      tradingSignal({ indicator: "BB", signal: "sell" }),
    ];
    render(<SignalPanel signals={signals} price={151.5} symbol="USDJPY" />);

    const badge = screen.getByText("買い優勢");
    expect(badge.className).toContain("badge-buy");
  });

  it("売りが多い場合は『売り優勢』", () => {
    const signals = [
      tradingSignal({ indicator: "RSI", signal: "sell" }),
      tradingSignal({ indicator: "MACD", signal: "sell" }),
      tradingSignal({ indicator: "BB", signal: "buy" }),
    ];
    render(<SignalPanel signals={signals} price={151.5} symbol="USDJPY" />);

    const badge = screen.getByText("売り優勢");
    expect(badge.className).toContain("badge-sell");
  });

  it("同数の場合は『中立』で色クラスを付けない", () => {
    const signals = [
      tradingSignal({ indicator: "RSI", signal: "buy" }),
      tradingSignal({ indicator: "MACD", signal: "sell" }),
    ];
    render(<SignalPanel signals={signals} price={151.5} symbol="USDJPY" />);

    const badge = screen.getByText("中立");
    expect(badge.className).not.toContain("badge-buy");
    expect(badge.className).not.toContain("badge-sell");
  });

  it("シグナルが 0 件の場合も『中立』", () => {
    render(<SignalPanel signals={[]} price={151.5} symbol="USDJPY" />);
    expect(screen.getByText("中立")).toBeTruthy();
  });
});

describe("SignalPanel — 件数集計", () => {
  it("買い・売りの件数をそれぞれ表示する", () => {
    const signals = [
      tradingSignal({ indicator: "RSI", signal: "buy" }),
      tradingSignal({ indicator: "MACD", signal: "buy" }),
      tradingSignal({ indicator: "BB", signal: "buy" }),
      tradingSignal({ indicator: "STOCH", signal: "sell" }),
    ];
    render(<SignalPanel signals={signals} price={151.5} symbol="USDJPY" />);

    const labels = Array.from(document.querySelectorAll(".stat-item")).map((el) => ({
      label: el.querySelector(".label")?.textContent,
      value: el.querySelector(".value")?.textContent,
    }));

    expect(labels).toContainEqual({ label: "買いシグナル", value: "3" });
    expect(labels).toContainEqual({ label: "売りシグナル", value: "1" });
  });
});

describe("SignalPanel — シグナル一覧", () => {
  it("0 件のときは案内文を表示する", () => {
    render(<SignalPanel signals={[]} price={151.5} symbol="USDJPY" />);
    expect(screen.getByText("現在シグナルはありません")).toBeTruthy();
  });

  it("指標名・理由・指標値を表示する", () => {
    render(
      <SignalPanel
        signals={[tradingSignal({ indicator: "RSI", signal: "buy", value: 28.4, reason: "売られすぎ" })]}
        price={151.5}
        symbol="USDJPY"
      />,
    );

    expect(screen.getByText("RSI")).toBeTruthy();
    expect(screen.getByText("売られすぎ")).toBeTruthy();
    expect(screen.getByText(/\(28\.4\)/)).toBeTruthy();
  });

  it("value が無いシグナルは括弧を表示しない", () => {
    const { container } = render(
      <SignalPanel
        signals={[tradingSignal({ indicator: "一目均衡表", signal: "buy", value: undefined, reason: "雲抜け" })]}
        price={151.5}
        symbol="USDJPY"
      />,
    );

    expect(container.textContent).not.toMatch(/\(\s*\)/);
  });

  it("買いシグナル行に signal-buy、売り行に signal-sell を付ける", () => {
    const { container } = render(
      <SignalPanel
        signals={[
          tradingSignal({ indicator: "RSI", signal: "buy" }),
          tradingSignal({ indicator: "MACD", signal: "sell" }),
        ]}
        price={151.5}
        symbol="USDJPY"
      />,
    );

    expect(container.querySelectorAll(".signal-buy")).toHaveLength(1);
    expect(container.querySelectorAll(".signal-sell")).toHaveLength(1);
  });

  it("方向を日本語ラベル（買い / 売り）で表示する", () => {
    render(
      <SignalPanel
        signals={[
          tradingSignal({ indicator: "RSI", signal: "buy" }),
          tradingSignal({ indicator: "MACD", signal: "sell" }),
        ]}
        price={151.5}
        symbol="USDJPY"
      />,
    );

    expect(screen.getByText("買い")).toBeTruthy();
    expect(screen.getByText("売り")).toBeTruthy();
  });
});
