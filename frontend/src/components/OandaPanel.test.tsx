/**
 * @file OandaPanel.test.tsx
 * @description `OandaPanel`（OANDA 発注パネル）のユニットテスト。
 *
 * 検証範囲:
 * - 口座ステータスの表示（未設定時のペーパー表記・残高・含み損益・案内文）
 * - 数量入力と買い / 売りボタンからの発注
 * - 送信中のボタン非活性化と onOrderPlaced コールバック
 * - 発注失敗時のエラー表示（コールバックを呼ばないこと）
 * - 直近注文の要約表示
 * - 注文履歴テーブル（0 件時の案内・行の内容・方向のクラス）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import OandaPanel from "./OandaPanel";
import * as api from "@/lib/api";
import { brokerOrder, oandaStatus } from "@/test/fixtures";

/** stat-item の label→value マップ */
function stats(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const el of Array.from(document.querySelectorAll(".stat-item"))) {
    out[el.querySelector(".label")?.textContent ?? ""] =
      el.querySelector(".value")?.textContent ?? "";
  }
  return out;
}

describe("OandaPanel — 口座ステータス", () => {
  it("未設定時はモードを『ペーパー』と表示し案内文を出す", () => {
    render(
      <OandaPanel
        status={oandaStatus({ configured: false, message: "OANDA 未設定のためペーパー取引です" })}
        orders={[]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(stats()["モード"]).toBe("ペーパー");
    expect(screen.getByText("OANDA 未設定のためペーパー取引です")).toBeTruthy();
  });

  it("設定済みの場合は実際のモードを表示し案内文を出さない", () => {
    render(
      <OandaPanel
        status={oandaStatus({ configured: true, mode: "live", message: "設定済み" })}
        orders={[]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(stats()["モード"]).toBe("live");
    expect(screen.queryByText("設定済み")).toBeNull();
  });

  it("残高を 3 桁区切り＋通貨で表示する", () => {
    render(
      <OandaPanel
        status={oandaStatus({ balance: 1234567, currency: "JPY" })}
        orders={[]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(stats()["残高"]).toBe("1,234,567 JPY");
  });

  it("含み損益を小数 2 桁で表示する", () => {
    render(
      <OandaPanel
        status={oandaStatus({ unrealized_pl: 12.3456 })}
        orders={[]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(stats()["含み損益"]).toBe("12.35");
  });

  it("含み損益が無い場合はその欄を表示しない", () => {
    render(
      <OandaPanel
        status={oandaStatus({ unrealized_pl: undefined })}
        orders={[]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(stats()["含み損益"]).toBeUndefined();
  });
});

describe("OandaPanel — 発注", () => {
  it("既定数量 1000 で買い注文を送る", async () => {
    const place = vi.spyOn(api, "placeOandaOrder").mockResolvedValue(brokerOrder());
    const onOrderPlaced = vi.fn();

    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={onOrderPlaced} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "買い" }));

    await waitFor(() => expect(place).toHaveBeenCalledWith("USDJPY", "buy", 1000));
    expect(onOrderPlaced).toHaveBeenCalledTimes(1);
  });

  it("入力した数量で売り注文を送る", async () => {
    const place = vi.spyOn(api, "placeOandaOrder").mockResolvedValue(brokerOrder({ side: "sell" }));

    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="EURUSD" onOrderPlaced={vi.fn()} />,
    );
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: "売り" }));

    await waitFor(() => expect(place).toHaveBeenCalledWith("EURUSD", "sell", 5000));
  });

  it("送信中は買い / 売りボタンを非活性化する", async () => {
    let resolve!: (o: Awaited<ReturnType<typeof api.placeOandaOrder>>) => void;
    vi.spyOn(api, "placeOandaOrder").mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );

    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "買い" }));

    expect((screen.getByRole("button", { name: "買い" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "売り" }) as HTMLButtonElement).disabled).toBe(true);

    await waitFor(async () => {
      resolve(brokerOrder());
    });
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "買い" }) as HTMLButtonElement).disabled).toBe(false),
    );
  });

  it("発注に成功すると直近注文の要約を表示する", async () => {
    vi.spyOn(api, "placeOandaOrder").mockResolvedValue(
      brokerOrder({ side: "buy", units: 1000, fill_price: 151.52, broker: "oanda" }),
    );

    const { container } = render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "買い" }));

    // 文字列が複数要素に分割されるためコンテナ全体のテキストで照合する
    await waitFor(() =>
      expect(container.textContent).toContain("直近注文: buy 1000 @ 151.52 (oanda)"),
    );
  });

  it("約定価格が無い場合はダッシュで表示する", async () => {
    vi.spyOn(api, "placeOandaOrder").mockResolvedValue(brokerOrder({ fill_price: undefined }));

    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "買い" }));

    await waitFor(() => expect(screen.getByText(/@ — /)).toBeTruthy());
  });

  it("発注に失敗した場合はエラーを表示しコールバックを呼ばない", async () => {
    vi.spyOn(api, "placeOandaOrder").mockRejectedValue(new Error("証拠金が不足しています"));
    const onOrderPlaced = vi.fn();

    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={onOrderPlaced} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "買い" }));

    await waitFor(() => expect(screen.getByText("証拠金が不足しています")).toBeTruthy());
    expect(onOrderPlaced).not.toHaveBeenCalled();
  });
});

describe("OandaPanel — 注文履歴", () => {
  it("0 件のときは案内文を表示する", () => {
    render(
      <OandaPanel status={oandaStatus()} orders={[]} symbol="USDJPY" onOrderPlaced={vi.fn()} />,
    );

    expect(screen.getByText("注文履歴はありません")).toBeTruthy();
    expect(document.querySelector(".data-table")).toBeNull();
  });

  it("注文をテーブルに一覧表示する", () => {
    render(
      <OandaPanel
        status={oandaStatus()}
        orders={[
          brokerOrder({ id: 1, symbol: "USDJPY", side: "buy", units: 1000, status: "filled" }),
          brokerOrder({ id: 2, symbol: "EURUSD", side: "sell", units: 2000, status: "pending" }),
        ]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(document.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(screen.getByText("filled")).toBeTruthy();
    expect(screen.getByText("pending")).toBeTruthy();
  });

  it("方向に応じて text-buy / text-sell クラスを付ける", () => {
    const { container } = render(
      <OandaPanel
        status={oandaStatus()}
        orders={[brokerOrder({ id: 1, side: "buy" }), brokerOrder({ id: 2, side: "sell" })]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(container.querySelectorAll("td.text-buy")).toHaveLength(1);
    expect(container.querySelectorAll("td.text-sell")).toHaveLength(1);
  });

  it("作成日時が無い注文はダッシュを表示する", () => {
    render(
      <OandaPanel
        status={oandaStatus()}
        orders={[brokerOrder({ created_at: undefined, fill_price: undefined })]}
        symbol="USDJPY"
        onOrderPlaced={vi.fn()}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});
