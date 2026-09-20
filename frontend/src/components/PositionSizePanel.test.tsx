/**
 * @file PositionSizePanel.test.tsx
 * @description `PositionSizePanel`（ポジションサイズ計算）のユニットテスト。
 *
 * 検証範囲:
 * - 初期値（残高 10,000 USD・リスク 1%・ストップ空欄）での取得パラメータ
 * - 入力変更（残高・リスク・ストップ）による再計算
 * - ストップ空欄時に stopPips を送らない（ATR 自動算出に委ねる）こと
 * - 計算中の表示と、結果（推奨ロット・ストップ・最大損失・利確目安）
 * - ATR ベースかどうかの注記
 * - 取得失敗時に結果を出さないこと
 * - 現在価格が読み取り専用で表示されること
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PositionSizePanel from "./PositionSizePanel";
import * as api from "@/lib/api";
import { positionSize } from "@/test/fixtures";

/** stat-item の label→value マップ */
function stats(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const el of Array.from(document.querySelectorAll(".stat-item"))) {
    out[el.querySelector(".label")?.textContent ?? ""] =
      el.querySelector(".value")?.textContent ?? "";
  }
  return out;
}

/** ラベル文字列から対応する input を取得する */
function input(label: string): HTMLInputElement {
  const group = Array.from(document.querySelectorAll(".form-group")).find((el) =>
    el.querySelector("label")?.textContent?.includes(label),
  );
  return group?.querySelector("input") as HTMLInputElement;
}

describe("PositionSizePanel — 取得パラメータ", () => {
  it("初期値で残高・リスク・日数を送り、ストップは送らない", async () => {
    const spy = vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());

    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("USDJPY", {
        accountBalance: 10000,
        riskPercent: 1,
        days: 200,
      }),
    );
  });

  it("ストップ入力があれば stopPips を数値で送る", async () => {
    const spy = vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());
    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.change(input("ストップ"), { target: { value: "35" } });

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith("USDJPY", {
        accountBalance: 10000,
        riskPercent: 1,
        days: 200,
        stopPips: 35,
      }),
    );
  });

  it("口座残高を変更すると再計算する", async () => {
    const spy = vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());
    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.change(input("口座残高"), { target: { value: "50000" } });

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "USDJPY",
        expect.objectContaining({ accountBalance: 50000 }),
      ),
    );
  });

  it("リスク % を変更すると再計算する", async () => {
    const spy = vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());
    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.change(input("リスク"), { target: { value: "2.5" } });

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(
        "USDJPY",
        expect.objectContaining({ riskPercent: 2.5 }),
      ),
    );
  });

  it("symbol / days の変更でも再計算する", async () => {
    const spy = vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());
    const { rerender } = render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    rerender(<PositionSizePanel symbol="EURUSD" price={1.1} days={90} />);

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith("EURUSD", expect.objectContaining({ days: 90 })),
    );
  });
});

describe("PositionSizePanel — 表示", () => {
  it("計算中はローディング文言を表示し、結果は出さない", () => {
    vi.spyOn(api, "getPositionSize").mockReturnValue(new Promise(() => {}));

    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);

    expect(screen.getByText("計算中...")).toBeTruthy();
    expect(screen.queryByText("推奨ロット")).toBeNull();
  });

  it("計算結果の 4 項目を表示する", async () => {
    vi.spyOn(api, "getPositionSize").mockResolvedValue(
      positionSize({
        recommended_lots: 0.35,
        stop_pips: 42,
        atr_based_stop: true,
        max_loss_usd: 100,
        suggested_take_profit_pips: 84,
      }),
    );

    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);

    await waitFor(() => expect(screen.getByText("推奨ロット")).toBeTruthy());
    expect(stats()).toEqual({
      推奨ロット: "0.35",
      ストップ: "42 pips (ATR)",
      最大損失: "$100",
      利確目安: "84 pips",
    });
  });

  it("ATR ベースでない場合は (ATR) の注記を付けない", async () => {
    vi.spyOn(api, "getPositionSize").mockResolvedValue(
      positionSize({ stop_pips: 30, atr_based_stop: false }),
    );

    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);

    await waitFor(() => expect(screen.getByText("30 pips")).toBeTruthy());
  });

  it("取得に失敗した場合は結果を表示しない", async () => {
    vi.spyOn(api, "getPositionSize").mockRejectedValue(new Error("500"));

    render(<PositionSizePanel symbol="USDJPY" price={151.5} days={200} />);

    await waitFor(() => expect(screen.queryByText("計算中...")).toBeNull());
    expect(screen.queryByText("推奨ロット")).toBeNull();
    // カード自体（フォーム）は残る
    expect(screen.getByText("ポジションサイズ計算")).toBeTruthy();
  });

  it("現在価格を読み取り専用で表示する", async () => {
    vi.spyOn(api, "getPositionSize").mockResolvedValue(positionSize());

    render(<PositionSizePanel symbol="USDJPY" price={151.52} days={200} />);
    await waitFor(() => expect(screen.queryByText("計算中...")).toBeNull());

    const priceInput = input("現在価格");
    expect(priceInput.value).toBe("151.52");
    expect(priceInput.readOnly).toBe(true);
  });
});
