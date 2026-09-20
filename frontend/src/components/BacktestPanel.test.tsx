/**
 * @file BacktestPanel.test.tsx
 * @description `BacktestPanel`（シグナルバックテストの要約カード）のユニットテスト。
 *
 * 検証範囲:
 * - props（symbol / days）を使った取得と、変更時の再取得
 * - データ未取得・取引 0 件・取得失敗時に非表示になること
 * - 勝率・トレード数・平均リターン・買い/売り内訳の表示
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import BacktestPanel from "./BacktestPanel";
import * as api from "@/lib/api";
import { signalBacktest } from "@/test/fixtures";

/** stat-item の label→value マップを作る */
function stats(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const el of Array.from(document.querySelectorAll(".stat-item"))) {
    const label = el.querySelector(".label")?.textContent ?? "";
    out[label] = el.querySelector(".value")?.textContent ?? "";
  }
  return out;
}

describe("BacktestPanel — データ取得", () => {
  it("props の symbol と days で取得する", async () => {
    const spy = vi.spyOn(api, "getSignalBacktest").mockResolvedValue(signalBacktest());
    render(<BacktestPanel symbol="EURUSD" days={365} />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("EURUSD", 365));
  });

  it("symbol が変わると再取得する", async () => {
    const spy = vi.spyOn(api, "getSignalBacktest").mockResolvedValue(signalBacktest());
    const { rerender } = render(<BacktestPanel symbol="USDJPY" days={200} />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    rerender(<BacktestPanel symbol="GBPUSD" days={200} />);

    await waitFor(() => expect(spy).toHaveBeenLastCalledWith("GBPUSD", 200));
  });
});

describe("BacktestPanel — 非表示条件", () => {
  it("取得前は何も描画しない", () => {
    vi.spyOn(api, "getSignalBacktest").mockReturnValue(new Promise(() => {}));
    const { container } = render(<BacktestPanel symbol="USDJPY" days={200} />);
    expect(container.textContent).toBe("");
  });

  it("トレード数が 0 の場合は描画しない", async () => {
    vi.spyOn(api, "getSignalBacktest").mockResolvedValue(signalBacktest({ total_trades: 0 }));
    const { container } = render(<BacktestPanel symbol="USDJPY" days={200} />);
    await waitFor(() => expect(container.textContent).toBe(""));
  });

  it("取得に失敗した場合も描画しない", async () => {
    vi.spyOn(api, "getSignalBacktest").mockRejectedValue(new Error("500"));
    const { container } = render(<BacktestPanel symbol="USDJPY" days={200} />);
    await waitFor(() => expect(container.textContent).toBe(""));
  });
});

describe("BacktestPanel — 表示内容", () => {
  it("勝率・トレード数・平均リターン・買い/売りを表示する", async () => {
    vi.spyOn(api, "getSignalBacktest").mockResolvedValue(
      signalBacktest({
        win_rate: 58.3,
        total_trades: 24,
        avg_return_pct: 0.42,
        buy_trades: 14,
        sell_trades: 10,
      }),
    );

    render(<BacktestPanel symbol="USDJPY" days={200} />);

    await waitFor(() => expect(screen.getByText("シグナルバックテスト")).toBeTruthy());
    expect(stats()).toEqual({
      勝率: "58.3%",
      トレード数: "24",
      平均リターン: "0.42%",
      "買い / 売り": "14 / 10",
    });
  });

  it("参考値である旨の注記を添える", async () => {
    vi.spyOn(api, "getSignalBacktest").mockResolvedValue(signalBacktest());
    render(<BacktestPanel symbol="USDJPY" days={200} />);

    await waitFor(() => expect(screen.getByText(/参考値/)).toBeTruthy());
  });
});
