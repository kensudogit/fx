/**
 * @file AIProDashboard.test.tsx
 * @description `AIProDashboard`（AI Pro の 7 機能）のユニットテスト。
 *
 * 検証範囲:
 * - タブ切り替え時の自動読み込みと、チャットタブでは自動読み込みしないこと
 * - 各タブの表示内容（シグナル / 市場ブリーフ / コーチング / バックテスト / リスク / ポートフォリオ）
 * - 残高入力の表示条件と API への反映
 * - 実行ボタン（チャットタブでは非表示・処理中の非活性化）
 * - エラーバナー
 * - チャット（送信・空入力の無視・Enter 送信・Shift+Enter の無視・セッション ID 維持）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AIProDashboard from "./AIProDashboard";
import * as api from "@/lib/api";
import * as fixtures from "@/test/fixtures";

/** すべての Pro API を正常系でモックする */
function mockApis() {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getProSignals").mockResolvedValue(fixtures.aiSignalResult());
  vi.spyOn(api, "getProMarketBrief").mockResolvedValue(fixtures.marketBrief());
  vi.spyOn(api, "getProCoaching").mockResolvedValue(fixtures.coachingResult());
  vi.spyOn(api, "getProBacktest").mockResolvedValue({
    symbol: "USDJPY",
    simple: fixtures.signalBacktest(),
    backtrader: {
      status: "success",
      total_return_pct: 8.5,
    } as Awaited<ReturnType<typeof api.getProBacktest>>["backtrader"],
    walk_forward: {
      status: "success",
      summary: {
        robustness_label: "頑健性は良好",
        avg_in_sample_win_rate: 60.1,
        avg_out_of_sample_win_rate: 55.4,
        window_count: 4,
      },
    } as Awaited<ReturnType<typeof api.getProBacktest>>["walk_forward"],
  });
  vi.spyOn(api, "getProRisk").mockResolvedValue(fixtures.advancedRisk());
  vi.spyOn(api, "getProPortfolio").mockResolvedValue(fixtures.portfolioOverview());
}

/** タブを切り替える */
function tab(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

describe("AIProDashboard — 初期表示とタブ", () => {
  it("初期タブ（AIシグナル）を自動で読み込む", async () => {
    mockApis();
    render(<AIProDashboard />);

    await waitFor(() => expect(api.getProSignals).toHaveBeenCalledWith("USDJPY"));
  });

  it("7 つのタブを表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(screen.getByText("AI売買シグナル — USDJPY")).toBeTruthy());

    for (const label of [
      "AIシグナル",
      "市場ブリーフ",
      "AIコーチング",
      "バックテスト",
      "リスク管理",
      "口座・通貨",
      "AIチャット",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it("タブを切り替えると対応する API を呼ぶ", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("市場ブリーフ");
    await waitFor(() => expect(api.getProMarketBrief).toHaveBeenCalledWith("USDJPY"));

    tab("AIコーチング");
    await waitFor(() => expect(api.getProCoaching).toHaveBeenCalledWith("USDJPY"));

    tab("口座・通貨");
    await waitFor(() => expect(api.getProPortfolio).toHaveBeenCalled());
  });

  it("チャットタブでは自動読み込みをしない", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalledTimes(1));

    tab("AIチャット");

    // 追加の読み込みが発生しないこと
    await waitFor(() => expect(screen.getByText("AI投資相談 — USDJPY")).toBeTruthy());
    expect(api.getProSignals).toHaveBeenCalledTimes(1);
  });

  it("チャットタブでは実行ボタンを表示しない", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(screen.getByRole("button", { name: "実行" })).toBeTruthy());

    tab("AIチャット");

    expect(screen.queryByRole("button", { name: "実行" })).toBeNull();
  });
});

describe("AIProDashboard — コントロール", () => {
  it("シンボル変更で再読み込みする", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(document.querySelector("select")!.options.length).toBe(2));

    fireEvent.change(document.querySelector("select")!, { target: { value: "EURUSD" } });

    await waitFor(() => expect(api.getProSignals).toHaveBeenLastCalledWith("EURUSD"));
  });

  it("残高入力はリスク管理タブでのみ表示し、API に反映する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    expect(screen.queryByPlaceholderText("残高")).toBeNull();

    tab("リスク管理");
    fireEvent.change(screen.getByPlaceholderText("残高"), { target: { value: "50000" } });

    await waitFor(() => expect(api.getProRisk).toHaveBeenLastCalledWith("USDJPY", 50000));
  });

  it("実行ボタンで再読み込みできる", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "実行" }));

    await waitFor(() => expect(api.getProSignals).toHaveBeenCalledTimes(2));
  });

  it("処理中はボタンを非活性化し進行表示を出す", async () => {
    mockApis();
    vi.spyOn(api, "getProSignals").mockReturnValue(new Promise(() => {}));

    render(<AIProDashboard />);

    await waitFor(() =>
      expect((screen.getByRole("button", { name: "分析中..." }) as HTMLButtonElement).disabled).toBe(
        true,
      ),
    );
    expect(screen.getByText("処理中...")).toBeTruthy();
  });

  it("失敗時はエラーバナーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getProSignals").mockRejectedValue(new Error("Pro プランが必要です"));

    render(<AIProDashboard />);

    await waitFor(() => expect(screen.getByText("Pro プランが必要です")).toBeTruthy());
  });
});

describe("AIProDashboard — 各タブの表示内容", () => {
  it("AIシグナル: アクション・信頼度・要約・ルールシグナルを表示する", async () => {
    mockApis();
    render(<AIProDashboard />);

    await waitFor(() => expect(screen.getByText("買い 71%")).toBeTruthy());
    expect(screen.getByText("ルール・ML・AI の 3 者が買いで一致しました。")).toBeTruthy();
    expect(screen.getByText("価格: 151.5")).toBeTruthy();
    expect(screen.getByText("RSI")).toBeTruthy();
  });

  it("市場ブリーフ: 要約・示唆・ニュース・SNS・経済を表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("市場ブリーフ");

    await waitFor(() => expect(screen.getByText("ドル高基調が継続しています。")).toBeTruthy());
    expect(screen.getByText(/押し目買い優先。/)).toBeTruthy();
    expect(screen.getByText("ニュース (bullish)")).toBeTruthy();
    expect(screen.getByText("SNS は強気優勢です。")).toBeTruthy();
    expect(screen.getByText("米指標は堅調です。")).toBeTruthy();
  });

  it("AIコーチング: 総評・改善提案・次の焦点を表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("AIコーチング");

    await waitFor(() => expect(screen.getByText("リスク管理は良好です。")).toBeTruthy());
    expect(screen.getByText("ロットを一定に保つ")).toBeTruthy();
    expect(screen.getByText(/損切り位置の一貫性/)).toBeTruthy();
  });

  it("バックテスト: 簡易・Backtrader・ウォークフォワードの 3 枠を表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("バックテスト");

    await waitFor(() => expect(screen.getByText("勝率 58.3% / 取引 24回")).toBeTruthy());
    expect(screen.getByText("リターン 8.5%")).toBeTruthy();
    expect(screen.getByText("頑健性は良好")).toBeTruthy();
    expect(screen.getByText(/IS勝率 60.1%/)).toBeTruthy();
  });

  it("バックテスト: Backtrader が失敗した場合はメッセージを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getProBacktest").mockResolvedValue({
      symbol: "USDJPY",
      simple: fixtures.signalBacktest(),
      backtrader: { status: "error", message: "backtrader 未インストール" },
      walk_forward: { status: "error", message: "データ不足" },
    } as Awaited<ReturnType<typeof api.getProBacktest>>);

    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());
    tab("バックテスト");

    await waitFor(() => expect(screen.getByText("backtrader 未インストール")).toBeTruthy());
    expect(screen.getByText("データ不足")).toBeTruthy();
  });

  it("リスク管理: 主要指標・資金配分・推奨事項を表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("リスク管理");

    await waitFor(() => expect(screen.getByText("12.4%")).toBeTruthy());
    expect(screen.getByText("0.4")).toBeTruthy();
    expect(screen.getByText("60%")).toBeTruthy();
    expect(screen.getByText("同方向ペアの同時保有を避ける")).toBeTruthy();
  });

  it("口座・通貨: 総残高と口座 / 通貨ペア一覧を表示する", async () => {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());

    tab("口座・通貨");

    await waitFor(() => expect(screen.getByText("総残高: 25,000 USD")).toBeTruthy());
    expect(screen.getByText("メイン")).toBeTruthy();
    expect(screen.getByText("oanda")).toBeTruthy();
    expect(screen.getByText("1.8%")).toBeTruthy();
  });

  it("口座・通貨: 30 日変化率の符号で色クラスを切り替える", async () => {
    mockApis();
    vi.spyOn(api, "getProPortfolio").mockResolvedValue(
      fixtures.portfolioOverview({
        pairs: [
          { symbol: "USDJPY", price: 151.5, change_30d_pct: 1.8, open_orders: 1 },
          { symbol: "EURUSD", price: 1.1, change_30d_pct: -0.5, open_orders: 0 },
        ],
      }),
    );

    const { container } = render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());
    tab("口座・通貨");

    await waitFor(() => expect(container.querySelectorAll("td.text-buy")).toHaveLength(1));
    expect(container.querySelectorAll("td.text-sell")).toHaveLength(1);
  });
});

describe("AIProDashboard — AI チャット", () => {
  /** チャットタブを開いた状態にする */
  async function openChat() {
    mockApis();
    render(<AIProDashboard />);
    await waitFor(() => expect(api.getProSignals).toHaveBeenCalled());
    tab("AIチャット");
    await waitFor(() => expect(screen.getByText("AI投資相談 — USDJPY")).toBeTruthy());
  }

  it("メッセージが無いときは案内文を表示する", async () => {
    await openChat();
    expect(screen.getByText(/自由に質問してください/)).toBeTruthy();
  });

  it("送信するとユーザー発言と AI の返答を表示する", async () => {
    await openChat();
    const send = vi.spyOn(api, "sendProChat").mockResolvedValue({
      session_id: 7,
      symbol: "USDJPY",
      reply: "押し目買いを推奨します。",
    });

    fireEvent.change(screen.getByPlaceholderText(/USDJPYの今週の戦略/), {
      target: { value: "今週の戦略は？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => expect(send).toHaveBeenCalledWith("今週の戦略は？", "USDJPY", undefined));
    await waitFor(() => expect(screen.getByText("押し目買いを推奨します。")).toBeTruthy());
    expect(screen.getByText("今週の戦略は？")).toBeTruthy();
  });

  it("送信後は入力欄を空にする", async () => {
    await openChat();
    vi.spyOn(api, "sendProChat").mockResolvedValue({
      session_id: 7,
      symbol: "USDJPY",
      reply: "ok",
    });
    const input = screen.getByPlaceholderText(/USDJPYの今週の戦略/) as HTMLInputElement;

    fireEvent.change(input, { target: { value: "質問" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => expect(input.value).toBe(""));
  });

  it("2 回目以降は session_id を引き継ぐ", async () => {
    await openChat();
    const send = vi.spyOn(api, "sendProChat").mockResolvedValue({
      session_id: 7,
      symbol: "USDJPY",
      reply: "ok",
    });
    const input = screen.getByPlaceholderText(/USDJPYの今週の戦略/);

    fireEvent.change(input, { target: { value: "1 回目" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));

    fireEvent.change(input, { target: { value: "2 回目" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => expect(send).toHaveBeenLastCalledWith("2 回目", "USDJPY", 7));
  });

  it("サーバーが履歴を返した場合はそれで置き換える", async () => {
    await openChat();
    vi.spyOn(api, "sendProChat").mockResolvedValue({
      session_id: 7,
      symbol: "USDJPY",
      reply: "ok",
      messages: [
        { role: "user", content: "過去の質問" },
        { role: "assistant", content: "過去の回答" },
      ],
    });

    fireEvent.change(screen.getByPlaceholderText(/USDJPYの今週の戦略/), {
      target: { value: "質問" },
    });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => expect(screen.getByText("過去の回答")).toBeTruthy());
    expect(screen.getByText("過去の質問")).toBeTruthy();
  });

  it("空入力・空白のみの入力では送信しない", async () => {
    await openChat();
    const send = vi.spyOn(api, "sendProChat");

    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    fireEvent.change(screen.getByPlaceholderText(/USDJPYの今週の戦略/), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    expect(send).not.toHaveBeenCalled();
  });

  it("Enter キーで送信し、Shift+Enter では送信しない", async () => {
    await openChat();
    const send = vi.spyOn(api, "sendProChat").mockResolvedValue({
      session_id: 7,
      symbol: "USDJPY",
      reply: "ok",
    });
    const input = screen.getByPlaceholderText(/USDJPYの今週の戦略/);

    fireEvent.change(input, { target: { value: "改行したい" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(send).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  });

  it("チャットが失敗した場合はエラーを表示する", async () => {
    await openChat();
    vi.spyOn(api, "sendProChat").mockRejectedValue(new Error("チャットエラー"));

    fireEvent.change(screen.getByPlaceholderText(/USDJPYの今週の戦略/), {
      target: { value: "質問" },
    });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => expect(screen.getByText("チャットエラー")).toBeTruthy());
  });
});
