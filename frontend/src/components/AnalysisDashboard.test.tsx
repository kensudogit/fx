/**
 * @file AnalysisDashboard.test.tsx
 * @description `AnalysisDashboard`（マーケット分析 8 タブ）のユニットテスト。
 *
 * 検証範囲:
 * - タブごとに対応する分析 API のみを呼ぶこと
 * - リスク管理タブの口座残高・リスク % 入力と API への反映（他タブでは非表示）
 * - シンボル変更・再分析ボタンによる再取得
 * - 読み込み中表示とエラーバナー
 * - 総合タブの複合スコア（符号・プラス記号）と 5 分野サマリー
 * - 相場環境タブ（レジーム・モメンタム・S/R・相関マトリクスの強弱クラス）
 * - リスク管理タブ（Readiness・リスクスコア・チェックリスト・シナリオ・配分）
 * - トレンド / ニュース / SNS / 経済 / ボラの各タブ表示
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AnalysisDashboard from "./AnalysisDashboard";
import * as api from "@/lib/api";
import * as fixtures from "@/test/fixtures";

/** すべての分析 API を正常系でモックする */
function mockApis() {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getIntelligenceReport").mockResolvedValue(fixtures.intelligenceReport());
  vi.spyOn(api, "getMarketAnalysis").mockResolvedValue(fixtures.marketAnalysis());
  vi.spyOn(api, "getRiskReport").mockResolvedValue(fixtures.riskReport());
  vi.spyOn(api, "getTrendPrediction").mockResolvedValue(fixtures.trendPrediction());
  vi.spyOn(api, "getAnalysisNews").mockResolvedValue(fixtures.newsAnalysis());
  vi.spyOn(api, "getSNSAnalysis").mockResolvedValue(fixtures.snsAnalysis());
  vi.spyOn(api, "getEconomicAnalysis").mockResolvedValue(fixtures.economicAnalysis());
  vi.spyOn(api, "getVolatilityPrediction").mockResolvedValue(fixtures.volatilityPrediction());
}

/** タブを切り替える */
function tab(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
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

describe("AnalysisDashboard — タブと API", () => {
  it("初期表示（総合タブ）で統合レポートを取得する", async () => {
    mockApis();
    render(<AnalysisDashboard />);

    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalledWith("USDJPY"));
  });

  it("8 つのタブを表示する", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());

    for (const label of [
      "総合",
      "相場環境",
      "リスク管理",
      "トレンド予測",
      "ニュース分析",
      "SNS分析",
      "経済指標",
      "ボラ予測",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });

  it.each([
    ["相場環境", "getMarketAnalysis"],
    ["トレンド予測", "getTrendPrediction"],
    ["ニュース分析", "getAnalysisNews"],
    ["SNS分析", "getSNSAnalysis"],
    ["経済指標", "getEconomicAnalysis"],
    ["ボラ予測", "getVolatilityPrediction"],
  ] as const)("%s タブでは %s を呼ぶ", async (label, method) => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());

    tab(label);

    await waitFor(() => expect(api[method]).toHaveBeenCalledWith("USDJPY"));
  });

  it("リスク管理タブは口座残高とリスク % を渡す", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());

    tab("リスク管理");

    await waitFor(() => expect(api.getRiskReport).toHaveBeenCalledWith("USDJPY", 10000, 1));
  });

  it("リスク入力を変更すると再取得する", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("リスク管理");
    await waitFor(() => expect(api.getRiskReport).toHaveBeenCalled());

    const inputs = Array.from(document.querySelectorAll(".inline-field input"));
    fireEvent.change(inputs[0], { target: { value: "50000" } });
    fireEvent.change(inputs[1], { target: { value: "2" } });

    await waitFor(() => expect(api.getRiskReport).toHaveBeenLastCalledWith("USDJPY", 50000, 2));
  });

  it("リスク入力はリスク管理タブでのみ表示する", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());

    expect(document.querySelectorAll(".inline-field")).toHaveLength(0);

    tab("リスク管理");

    expect(document.querySelectorAll(".inline-field")).toHaveLength(2);
  });

  it("シンボル変更で再取得する", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(document.querySelector("select")!.options.length).toBe(2));

    fireEvent.change(document.querySelector("select")!, { target: { value: "EURUSD" } });

    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenLastCalledWith("EURUSD"));
  });

  it("再分析ボタンで再取得する", async () => {
    mockApis();
    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "再分析" }));

    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalledTimes(2));
  });
});

describe("AnalysisDashboard — 読み込みとエラー", () => {
  it("初回読み込み中はローディング表示", () => {
    mockApis();
    vi.spyOn(api, "getIntelligenceReport").mockReturnValue(new Promise(() => {}));

    render(<AnalysisDashboard />);

    expect(screen.getByText("分析を実行中...")).toBeTruthy();
    expect((screen.getByRole("button", { name: "分析中..." }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("失敗時はエラーバナーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getIntelligenceReport").mockRejectedValue(new Error("分析に失敗しました"));

    render(<AnalysisDashboard />);

    await waitFor(() => expect(screen.getByText("分析に失敗しました")).toBeTruthy());
  });
});

describe("AnalysisDashboard — 総合タブ", () => {
  it("見通しラベルと複合スコアを表示する", async () => {
    mockApis();
    render(<AnalysisDashboard />);

    await waitFor(() => expect(screen.getByText("やや強気")).toBeTruthy());
    expect(screen.getByText(/\+.*35/)).toBeTruthy();
  });

  it("負のスコアにはプラス記号を付けない", async () => {
    mockApis();
    vi.spyOn(api, "getIntelligenceReport").mockResolvedValue(
      fixtures.intelligenceReport({ composite_score: -20, outlook_label: "やや弱気" }),
    );

    const { container } = render(<AnalysisDashboard />);

    await waitFor(() => expect(screen.getByText("やや弱気")).toBeTruthy());
    const score = container.querySelector(".composite-score") as HTMLElement;
    expect(score.textContent).toBe("-20");
    expect(score.getAttribute("data-sign")).toBe("-1");
  });

  it("5 分野のサマリーカードを表示する", async () => {
    mockApis();
    render(<AnalysisDashboard />);

    await waitFor(() => expect(screen.getByText(/トレンド予測/)).toBeTruthy());
    for (const title of ["トレンド予測", "ニュース", "SNS", "経済指標", "ボラティリティ"]) {
      expect(
        Array.from(document.querySelectorAll(".summary-card h3")).some((h) =>
          h.textContent?.startsWith(title),
        ),
      ).toBe(true);
    }
  });

  it("強気 / 弱気のバイアスをバッジ色で区別する", async () => {
    mockApis();
    const { container } = render(<AnalysisDashboard />);

    await waitFor(() => expect(container.querySelector(".summary-card")).toBeTruthy());
    expect(container.querySelectorAll(".badge-buy").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".badge-sell").length).toBeGreaterThan(0);
  });
});

describe("AnalysisDashboard — 相場環境タブ", () => {
  /** 相場環境タブを開く */
  async function openMarket() {
    mockApis();
    const view = render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("相場環境");
    await waitFor(() => expect(screen.getByText("明確なトレンド（強度 72/100）")).toBeTruthy());
    return view;
  }

  it("レジームを日本語ラベルで表示する", async () => {
    await openMarket();
    expect(screen.getByText("トレンド")).toBeTruthy();
  });

  it("モメンタム指標を表示する", async () => {
    await openMarket();
    expect(screen.getByText("強い上昇モメンタム（スコア 62）")).toBeTruthy();
    expect(stats()["RSI"]).toBe("61.7");
    expect(stats()["5日ROC"]).toBe("0.8%");
  });

  it("サポート / レジスタンスと距離を表示する", async () => {
    await openMarket();
    expect(stats()["最寄サポート"]).toBe("150.2 (130 pips)");
    expect(stats()["最寄レジスタンス"]).toBe("152.8 (130 pips)");
  });

  it("サポートが無い場合はダッシュを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getMarketAnalysis").mockResolvedValue(
      fixtures.marketAnalysis({
        key_levels: {
          current_price: 151.5,
          nearest_support: null,
          nearest_resistance: null,
          supports: [],
          resistances: [],
        },
      }),
    );

    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("相場環境");

    await waitFor(() => expect(stats()["最寄サポート"]).toBe("—"));
  });

  it("相関マトリクスで対角線と高相関を区別する", async () => {
    const { container } = await openMarket();

    expect(container.querySelectorAll("td.corr-self")).toHaveLength(2);
    // |−0.72| ≥ 0.7 のセルは corr-high
    expect(container.querySelectorAll("td.corr-high")).toHaveLength(2);
    expect(screen.getAllByText("-0.72")).toHaveLength(2);
  });

  it("イベントリスクのアラートを一覧表示する", async () => {
    await openMarket();
    expect(screen.getByText(/2026-01-05 — FOMC（あと 30h）/)).toBeTruthy();
  });
});

describe("AnalysisDashboard — リスク管理タブ", () => {
  /** リスク管理タブを開く */
  async function openRisk() {
    mockApis();
    const view = render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("リスク管理");
    await waitFor(() => expect(screen.getByText("条件付きでエントリー可")).toBeTruthy());
    return view;
  }

  it("Readiness バナーをレベル別クラスで表示する", async () => {
    const { container } = await openRisk();
    expect(container.querySelector(".readiness-caution")).toBeTruthy();
  });

  it("リスクスコアと VaR を表示する", async () => {
    const { container } = await openRisk();

    const score = container.querySelector(".risk-score-display") as HTMLElement;
    expect(score.textContent).toBe("48/100");
    expect(score.getAttribute("data-level")).toBe("medium");
    expect(stats()["1日VaR (95%)"]).toBe("$120");
  });

  it("エントリー前チェックリストを状態別クラスで表示する", async () => {
    const { container } = await openRisk();

    expect(screen.getByText("MTF 整合")).toBeTruthy();
    expect(container.querySelector(".checklist-ok")).toBeTruthy();
  });

  it("シナリオ分析とストレステストを表示する", async () => {
    await openRisk();

    expect(stats()["上振れ"]).toBe("153.2 (+170 pips)");
    expect(stats()["下振れ"]).toBe("149.8 (-170 pips)");
    expect(screen.getByText("3 連敗しても運用継続可能です。")).toBeTruthy();
  });

  it("リスク予算と資金配分テーブルを表示する", async () => {
    await openRisk();

    expect(stats()["1トレード上限"]).toBe("$100");
    expect(stats()["同時保有上限"]).toBe("$300 / 最大3ポジ");
    expect(screen.getByText("同方向ペアの同時保有を避ける")).toBeTruthy();
  });
});

describe("AnalysisDashboard — 個別分析タブ", () => {
  /** 指定タブを開いて完了を待つ */
  async function open(label: string, expectText: string) {
    mockApis();
    const view = render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab(label);
    await waitFor(() => expect(screen.getByText(expectText)).toBeTruthy());
    return view;
  }

  it("トレンド予測: 価格・期間・信頼度・根拠・ML 精度を表示する", async () => {
    await open("トレンド予測", "SMA20 が SMA50 を上抜け");

    expect(stats()["現在価格"]).toBe("151.5");
    expect(stats()["予測期間"]).toBe("5日");
    expect(stats()["信頼度"]).toBe("64%");
    expect(screen.getByText(/ML \(RandomForest\): 強気 \/ テスト精度 61.2%/)).toBeTruthy();
  });

  it("ニュース分析: ML スコアとヘッドラインを表示する", async () => {
    await open("ニュース分析", "ML 判定は強気です。");

    expect(stats()["MLスコア"]).toBe("0.4");
    expect(stats()["強気ヒット"]).toBe("7");
    expect(screen.getByText("OpenAI は中立と判断しました。")).toBeTruthy();
    expect((screen.getByText("ドル円続伸") as HTMLAnchorElement).getAttribute("href")).toBe(
      "https://example.com/n1",
    );
  });

  it("ニュース分析: URL の無い記事はリンクにしない", async () => {
    mockApis();
    vi.spyOn(api, "getAnalysisNews").mockResolvedValue(
      fixtures.newsAnalysis({ articles: [{ title: "リンクなし記事" }] }),
    );

    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("ニュース分析");

    await waitFor(() => expect(screen.getByText("リンクなし記事")).toBeTruthy());
    expect(screen.getByText("リンクなし記事").tagName).not.toBe("A");
  });

  it("SNS分析: 投稿統計と投稿一覧を表示する", async () => {
    await open("SNS分析", "円高警戒の投稿が目立ちます。");

    expect(stats()["投稿数"]).toBe("12");
    expect(stats()["エンゲージメント"]).toBe("中");
    expect(screen.getByText("r/forex")).toBeTruthy();
  });

  it("経済指標: 指標テーブルと高影響イベントを表示する", async () => {
    await open("経済指標", "米指標優位の構図です。");

    expect(screen.getByText("CPI")).toBeTruthy();
    expect(screen.getByText("3.1 %")).toBeTruthy();
    expect(screen.getByText("ポジティブ")).toBeTruthy();
    expect(screen.getByText("72時間以内の高影響イベント")).toBeTruthy();
  });

  it("経済指標: 高影響イベントが無ければ見出しを出さない", async () => {
    mockApis();
    vi.spyOn(api, "getEconomicAnalysis").mockResolvedValue(
      fixtures.economicAnalysis({ high_impact_alerts: [] }),
    );

    render(<AnalysisDashboard />);
    await waitFor(() => expect(api.getIntelligenceReport).toHaveBeenCalled());
    tab("経済指標");

    await waitFor(() => expect(screen.getByText("米指標優位の構図です。")).toBeTruthy());
    expect(screen.queryByText("72時間以内の高影響イベント")).toBeNull();
  });

  it("ボラ予測: 現在値と予測値・モデル情報を表示する", async () => {
    await open("ボラ予測", "当面はボラティリティ低位で推移する見込みです。");

    expect(stats()["ATR"]).toBe("0.82");
    expect(stats()["予測ATR"]).toBe("0.9");
    expect(stats()["レジーム"]).toBe("平常");
    expect(screen.getByText("モデル: GradientBoosting (success)")).toBeTruthy();
  });
});
