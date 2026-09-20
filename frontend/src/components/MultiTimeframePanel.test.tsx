/**
 * @file MultiTimeframePanel.test.tsx
 * @description `MultiTimeframePanel`（日足・4 時間足のトレンド整合）のユニットテスト。
 *
 * 検証範囲:
 * - symbol による取得と再取得
 * - 未取得・取得失敗時に非表示になること
 * - 整合ラベルと各時間足のトレンドバッジ（bullish / bearish / neutral のクラス）
 * - 時間足の日本語表記（1d→日足 / 4h→4時間足）
 * - RSI 未取得時のダッシュ表示、signal_bias の日本語変換
 * - 片方の時間足が欠けている場合の描画
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import MultiTimeframePanel from "./MultiTimeframePanel";
import * as api from "@/lib/api";
import { multiTimeframe } from "@/test/fixtures";

describe("MultiTimeframePanel — データ取得", () => {
  it("symbol を指定して取得する", async () => {
    const spy = vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(multiTimeframe());
    render(<MultiTimeframePanel symbol="EURUSD" />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("EURUSD"));
  });

  it("symbol が変わると再取得する", async () => {
    const spy = vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(multiTimeframe());
    const { rerender } = render(<MultiTimeframePanel symbol="USDJPY" />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    rerender(<MultiTimeframePanel symbol="GBPUSD" />);

    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("GBPUSD"));
  });

  it("取得前・取得失敗時は何も描画しない", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockRejectedValue(new Error("500"));
    const { container } = render(<MultiTimeframePanel symbol="USDJPY" />);
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});

describe("MultiTimeframePanel — 表示内容", () => {
  it("整合ラベルを表示する", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(
      multiTimeframe({ alignment_label: "日足・4H ともに上昇方向で一致" }),
    );

    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() =>
      expect(screen.getByText("日足・4H ともに上昇方向で一致")).toBeTruthy(),
    );
  });

  it("時間足を日本語（日足 / 4時間足）で表示する", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(multiTimeframe());
    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("日足")).toBeTruthy());
    expect(screen.getByText("4時間足")).toBeTruthy();
  });

  it("トレンドに応じたバッジクラスを付ける", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(multiTimeframe());
    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("上昇")).toBeTruthy());
    expect(screen.getByText("上昇").className).toContain("badge-buy");
    expect(screen.getByText("下降").className).toContain("badge-sell");
  });

  it("未知のトレンド値ではクラスを付けない", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(
      multiTimeframe({
        timeframes: {
          "1d": { trend: "unknown", label: "判定不能", rsi: 50, signal_bias: "none" },
        },
      }),
    );

    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("判定不能")).toBeTruthy());
    expect(screen.getByText("判定不能").className.trim()).toBe("badge");
  });

  it("signal_bias を日本語（買い / 売り / 中立）に変換する", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(multiTimeframe());
    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("シグナル: 買い")).toBeTruthy());
    expect(screen.getByText("シグナル: 売り")).toBeTruthy();
  });

  it("buy / sell 以外の signal_bias は『中立』にまとめる", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(
      multiTimeframe({
        timeframes: {
          "1d": { trend: "neutral", label: "中立", rsi: 50, signal_bias: "hold" },
        },
      }),
    );

    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("シグナル: 中立")).toBeTruthy());
  });

  it("RSI が無い場合はダッシュを表示する", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(
      multiTimeframe({
        timeframes: {
          "1d": { trend: "bullish", label: "上昇", rsi: null, signal_bias: "buy" },
        },
      }),
    );

    render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(screen.getByText("RSI —")).toBeTruthy());
  });

  it("4 時間足のデータが無い場合はその枠を描画しない", async () => {
    vi.spyOn(api, "getMultiTimeframe").mockResolvedValue(
      multiTimeframe({
        timeframes: {
          "1d": { trend: "bullish", label: "上昇", rsi: 61.7, signal_bias: "buy" },
        },
      }),
    );

    const { container } = render(<MultiTimeframePanel symbol="USDJPY" />);

    await waitFor(() => expect(container.querySelectorAll(".mtf-item")).toHaveLength(1));
    expect(screen.queryByText("4時間足")).toBeNull();
  });
});
