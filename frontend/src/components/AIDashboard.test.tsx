/**
 * @file AIDashboard.test.tsx
 * @description `AIDashboard`（OpenAI 統合分析ダッシュボード）のユニットテスト。
 *
 * 検証範囲:
 * - 初期表示（シンボル一覧・AI ステータス・未実行時の案内）
 * - タブごとに対応する AI API のみを呼ぶこと
 * - 口座残高入力の表示条件（リスク・総合レポートタブのみ）と API への反映
 * - AI ステータスバッジ（未設定 / 接続準備完了 / プランで無効）
 * - 分析中の表示とエラーバナー
 * - 各パネルの内容（ニュース・ファンダ・売買判断・リスク・総合レポート）
 * - ラベル変換（センチメント・アクション・リスクレベル）とフォールバック注記
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AIDashboard from "./AIDashboard";
import * as api from "@/lib/api";
import * as authContext from "@/context/AuthContext";
import * as fixtures from "@/test/fixtures";
import type { AuthSession } from "@/lib/api";
import type { AINewsAnalysis } from "@/types";

/** useAuth を差し替える */
function mockAuth(session: AuthSession | null = null) {
  vi.spyOn(authContext, "useAuth").mockReturnValue({
    saasEnabled: true,
    session,
    loading: false,
    refresh: vi.fn(),
    logout: vi.fn(),
  });
}

/** 共通の API モックを設置する */
function mockApis(aiConfigured = true) {
  mockAuth();
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getAIStatus").mockResolvedValue({
    configured: aiConfigured,
    model: "gpt-4o-mini",
  } as Awaited<ReturnType<typeof api.getAIStatus>>);
}

/** 初期描画の完了を待つ */
async function waitReady() {
  await waitFor(() => expect(screen.getByRole("heading", { name: /AI 分析/ })).toBeTruthy());
}

/** 「AI分析を実行」ボタンを押す */
function run() {
  fireEvent.click(screen.getByRole("button", { name: "AI分析を実行" }));
}

describe("AIDashboard — 初期表示", () => {
  it("シンボル一覧をセレクトに反映する", async () => {
    mockApis();
    render(<AIDashboard />);
    await waitReady();

    await waitFor(() =>
      expect(Array.from(document.querySelector("select")!.options).map((o) => o.value)).toEqual([
        "USDJPY",
        "EURUSD",
      ]),
    );
  });

  it("未実行のときは操作案内を表示する", async () => {
    mockApis();
    render(<AIDashboard />);
    await waitReady();

    expect(screen.getByText(/「AI分析を実行」ボタンを押すと/)).toBeTruthy();
  });

  it("既定タブは総合レポート", async () => {
    mockApis();
    render(<AIDashboard />);
    await waitReady();

    expect(screen.getByRole("button", { name: "総合レポート" }).className).toContain("active");
  });

  it("5 つのタブを表示する", async () => {
    mockApis();
    render(<AIDashboard />);
    await waitReady();

    for (const label of ["総合レポート", "ニュース収集", "経済指標分析", "売買判断", "リスク管理"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });
});

describe("AIDashboard — AI ステータスバッジ", () => {
  it("API キー未設定なら警告を表示する", async () => {
    mockApis(false);
    render(<AIDashboard />);

    await waitFor(() => expect(screen.getByText(/OPENAI_API_KEY が未設定です/)).toBeTruthy());
  });

  it("設定済みなら接続準備完了を表示する", async () => {
    mockApis(true);
    render(<AIDashboard />);

    await waitFor(() => expect(screen.getByText(/接続準備完了/)).toBeTruthy());
  });

  it("ステータス取得に失敗した場合は未設定として扱う", async () => {
    mockAuth();
    vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: [] });
    vi.spyOn(api, "getAIStatus").mockRejectedValue(new Error("500"));

    render(<AIDashboard />);

    await waitFor(() => expect(screen.getByText(/OPENAI_API_KEY が未設定です/)).toBeTruthy());
  });

  it("プランで AI が無効な場合はその旨を表示する", async () => {
    mockApis();
    mockAuth(fixtures.authSession({ features: { ai: false } }));

    render(<AIDashboard />);

    await waitFor(() => expect(screen.getByText(/プランで AI が無効です/)).toBeTruthy());
  });
});

describe("AIDashboard — タブごとの API 呼び出し", () => {
  it.each([
    ["ニュース収集", "getAINews"],
    ["経済指標分析", "getAIFundamentalAnalysis"],
    ["売買判断", "getAITradingDecision"],
  ] as const)("%s タブでは %s のみを呼ぶ", async (tab, method) => {
    mockApis();
    const news = vi.spyOn(api, "getAINews").mockResolvedValue(fixtures.aiNews());
    const fundamental = vi
      .spyOn(api, "getAIFundamentalAnalysis")
      .mockResolvedValue(fixtures.aiFundamental());
    const trading = vi
      .spyOn(api, "getAITradingDecision")
      .mockResolvedValue(fixtures.aiTradingDecision());
    const report = vi.spyOn(api, "getAIReport").mockResolvedValue(fixtures.aiFullReport());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: tab }));
    run();

    const spies = { getAINews: news, getAIFundamentalAnalysis: fundamental, getAITradingDecision: trading };
    await waitFor(() => expect(spies[method]).toHaveBeenCalledWith("USDJPY"));
    expect(report).not.toHaveBeenCalled();
  });

  it("リスク管理タブは口座残高を渡す", async () => {
    mockApis();
    const risk = vi.spyOn(api, "getAIRisk").mockResolvedValue(fixtures.aiRisk());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "リスク管理" }));
    fireEvent.change(screen.getByPlaceholderText("口座残高"), { target: { value: "50000" } });
    run();

    await waitFor(() => expect(risk).toHaveBeenCalledWith("USDJPY", 50000));
  });

  it("総合レポートタブは既定残高 10000 で呼ぶ", async () => {
    mockApis();
    const report = vi.spyOn(api, "getAIReport").mockResolvedValue(fixtures.aiFullReport());

    render(<AIDashboard />);
    await waitReady();
    run();

    await waitFor(() => expect(report).toHaveBeenCalledWith("USDJPY", 10000));
  });

  it("選択したシンボルで分析する", async () => {
    mockApis();
    const report = vi.spyOn(api, "getAIReport").mockResolvedValue(fixtures.aiFullReport());

    render(<AIDashboard />);
    await waitReady();
    await waitFor(() => expect(document.querySelector("select")!.options.length).toBe(2));
    fireEvent.change(document.querySelector("select")!, { target: { value: "EURUSD" } });
    run();

    await waitFor(() => expect(report).toHaveBeenCalledWith("EURUSD", 10000));
  });

  it("残高入力はリスク・総合レポートタブでのみ表示する", async () => {
    mockApis();
    render(<AIDashboard />);
    await waitReady();

    expect(screen.getByPlaceholderText("口座残高")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "ニュース収集" }));
    expect(screen.queryByPlaceholderText("口座残高")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "リスク管理" }));
    expect(screen.getByPlaceholderText("口座残高")).toBeTruthy();
  });
});

describe("AIDashboard — 実行中・エラー", () => {
  it("分析中はローディング文言を表示しボタンを非活性化する", async () => {
    mockApis();
    vi.spyOn(api, "getAIReport").mockReturnValue(new Promise(() => {}));

    render(<AIDashboard />);
    await waitReady();
    run();

    expect(screen.getByText(/OpenAI で分析中です/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "分析中..." }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("失敗時はエラーバナーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAIReport").mockRejectedValue(new Error("AI分析がタイムアウトしました"));

    render(<AIDashboard />);
    await waitReady();
    run();

    await waitFor(() => expect(screen.getByText("AI分析がタイムアウトしました")).toBeTruthy());
  });
});

describe("AIDashboard — ニュースパネル", () => {
  it("センチメント・スコア・要約・キートピック・記事一覧を表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAINews").mockResolvedValue(fixtures.aiNews());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "ニュース収集" }));
    run();

    await waitFor(() => expect(screen.getByText("ニュース要約")).toBeTruthy());
    expect(screen.getByText("強気")).toBeTruthy();
    expect(screen.getByText("0.62")).toBeTruthy();
    expect(screen.getByText("米金利上昇観測からドル買いが優勢です。")).toBeTruthy();
    expect(screen.getByText("FOMC")).toBeTruthy();
    expect(screen.getByText("収集ニュース (1件)")).toBeTruthy();
    expect(
      (screen.getByText("ドル円が年初来高値を更新") as HTMLAnchorElement).getAttribute("href"),
    ).toBe("https://example.com/a");
  });

  it("未知のセンチメント値はそのまま表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAINews").mockResolvedValue(fixtures.aiNews({ sentiment: "mixed" as AINewsAnalysis["sentiment"] }));

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "ニュース収集" }));
    run();

    await waitFor(() => expect(screen.getByText("mixed")).toBeTruthy());
  });

  it("キートピックが空なら見出しを出さない", async () => {
    mockApis();
    vi.spyOn(api, "getAINews").mockResolvedValue(fixtures.aiNews({ key_topics: [] }));

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "ニュース収集" }));
    run();

    await waitFor(() => expect(screen.getByText("ニュース要約")).toBeTruthy());
    expect(screen.queryByText("キートピック:")).toBeNull();
  });
});

describe("AIDashboard — 売買判断パネル", () => {
  it("アクションを日本語ラベルとバッジクラスで表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAITradingDecision").mockResolvedValue(
      fixtures.aiTradingDecision({ action: "buy" }),
    );

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "売買判断" }));
    run();

    await waitFor(() => expect(screen.getByText("買い")).toBeTruthy());
    expect(screen.getByText("買い").className).toContain("badge-buy");
  });

  it("hold は『様子見』でバッジ色を付けない", async () => {
    mockApis();
    vi.spyOn(api, "getAITradingDecision").mockResolvedValue(
      fixtures.aiTradingDecision({ action: "hold" }),
    );

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "売買判断" }));
    run();

    await waitFor(() => expect(screen.getByText("様子見")).toBeTruthy());
    expect(screen.getByText("様子見").className.trim()).toBe("badge");
  });

  it("エントリー・利確・損切り・RR比・根拠を表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAITradingDecision").mockResolvedValue(fixtures.aiTradingDecision());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "売買判断" }));
    run();

    await waitFor(() => expect(screen.getByText("151.5")).toBeTruthy());
    expect(screen.getByText("153")).toBeTruthy();
    expect(screen.getByText("150.8")).toBeTruthy();
    expect(screen.getByText("2.1")).toBeTruthy();
    expect(screen.getByText("上位足のトレンドに沿った押し目買いです。")).toBeTruthy();
  });

  it("警告一覧を表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAITradingDecision").mockResolvedValue(fixtures.aiTradingDecision());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "売買判断" }));
    run();

    await waitFor(() =>
      expect(screen.getByText("FOMC 前はボラティリティに注意")).toBeTruthy(),
    );
  });

  it("fallback フラグがある場合はルールベース参考値である旨を注記する", async () => {
    mockApis();
    vi.spyOn(api, "getAITradingDecision").mockResolvedValue(
      fixtures.aiTradingDecision({ fallback: true } as never),
    );

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "売買判断" }));
    run();

    await waitFor(() => expect(screen.getByText(/ルールベース参考値/)).toBeTruthy());
  });
});

describe("AIDashboard — リスクパネル", () => {
  it("リスクレベルを日本語に変換して主要指標を表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAIRisk").mockResolvedValue(fixtures.aiRisk());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "リスク管理" }));
    run();

    await waitFor(() => expect(screen.getByText("中")).toBeTruthy());
    expect(screen.getByText("48/100")).toBeTruthy();
    expect(screen.getByText("2% ($200)")).toBeTruthy();
    expect(screen.getByText("3x")).toBeTruthy();
    expect(screen.getByText("150.8 / 153")).toBeTruthy();
  });

  it("推奨事項と避けるべき条件を一覧表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAIRisk").mockResolvedValue(fixtures.aiRisk());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "リスク管理" }));
    run();

    await waitFor(() => expect(screen.getByText("ロットを抑える")).toBeTruthy());
    expect(screen.getByText("指標発表の直前")).toBeTruthy();
  });
});

describe("AIDashboard — ファンダメンタル / 総合レポート", () => {
  it("ファンダパネルは概要・通貨別分析・指標テーブルを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAIFundamentalAnalysis").mockResolvedValue(fixtures.aiFundamental());

    render(<AIDashboard />);
    await waitReady();
    fireEvent.click(screen.getByRole("button", { name: "経済指標分析" }));
    run();

    await waitFor(() => expect(screen.getByText("米経済指標は堅調です。")).toBeTruthy());
    expect(screen.getByText("USD は金利差で優位。")).toBeTruthy();
    expect(screen.getByText("JPY は緩和継続で軟調。")).toBeTruthy();
    expect(screen.getByText("予想超え")).toBeTruthy();
  });

  it("総合レポートは売買判断・ニュース・ファンダ・リスクを 1 画面に集約する", async () => {
    mockApis();
    vi.spyOn(api, "getAIReport").mockResolvedValue(fixtures.aiFullReport());

    render(<AIDashboard />);
    await waitReady();
    run();

    // 「売買判断」「リスク管理」はタブ名とも重なるため、見出し（h2）で照合する
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 2, name: "売買判断" })).toBeTruthy(),
    );
    expect(screen.getByRole("heading", { level: 2, name: "ニュース要約" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "経済指標 AI 分析" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "リスク管理" })).toBeTruthy();
  });
});
