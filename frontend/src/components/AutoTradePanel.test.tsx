/**
 * @file AutoTradePanel.test.tsx
 * @description `AutoTradePanel`（自動取引エンジン）のユニットテスト。
 *
 * 実際の発注につながる操作を含むため、確認ダイアログの挙動を重点的に検証する。
 *
 * 検証範囲:
 * - 初期ロード（設定・ステータス・シンボル・プリセット）と更新
 * - プリセット適用・オートセレクト（提案のみ / 適用）
 * - 運用前シミュレーション（実行中・成功・失敗）
 * - ドライラン評価と評価結果の表示
 * - 単一 / 全シンボル実行の確認ダイアログ（キャンセル時は実行しない）
 * - 自動取引が無効なときの実行ボタン非活性化
 * - 設定変更（チェックボックス即時保存・数値入力は onBlur 保存）
 * - 通貨ペア / シグナルソースのチップ切り替えと「最後の 1 つは外せない」ガード
 * - パフォーマンス・オープンポジション・実行ログの表示
 * - エラー表示
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AutoTradePanel from "./AutoTradePanel";
import * as api from "@/lib/api";
import * as fixtures from "@/test/fixtures";
import type { AutoTradeConfig, AutoTradeStatus } from "@/types";

/** API を正常系でモックする */
function mockApis(over: { config?: Partial<AutoTradeConfig>; status?: Partial<AutoTradeStatus> } = {}) {
  vi.spyOn(api, "getSymbols").mockResolvedValue({ symbols: ["USDJPY", "EURUSD"] });
  vi.spyOn(api, "getAutoTradePresets").mockResolvedValue({
    presets: [
      fixtures.autoTradePreset(),
      fixtures.autoTradePreset({ id: "aggressive", label: "アグレッシブ", description: "高頻度" }),
    ],
  });
  vi.spyOn(api, "getAutoTradeConfig").mockResolvedValue({
    config: fixtures.autoTradeConfig(over.config),
    defaults: fixtures.autoTradeConfig(),
  });
  vi.spyOn(api, "getAutoTradeStatus").mockResolvedValue(fixtures.autoTradeStatus(over.status));
}

/** 読み込み完了を待つ */
async function waitLoaded() {
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "自動取引エンジン" })).toBeTruthy(),
  );
}

/** ラベル文字列から数値入力を取得する */
function numberInput(label: string): HTMLInputElement {
  const el = Array.from(document.querySelectorAll("label")).find((l) =>
    l.textContent?.startsWith(label),
  );
  return el?.querySelector("input") as HTMLInputElement;
}

/** テキストからチェックボックスを取得する */
function checkbox(label: string): HTMLInputElement {
  const row = Array.from(document.querySelectorAll(".checkbox-row")).find((l) =>
    l.textContent?.includes(label),
  );
  return row?.querySelector("input") as HTMLInputElement;
}

describe("AutoTradePanel — 初期ロード", () => {
  it("読み込み中は専用メッセージを表示する", () => {
    mockApis();
    vi.spyOn(api, "getAutoTradeConfig").mockReturnValue(new Promise(() => {}));

    render(<AutoTradePanel />);

    expect(screen.getByText("自動取引設定を読み込み中...")).toBeTruthy();
  });

  it("設定・ステータス・シンボル・プリセットを取得する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(api.getAutoTradeConfig).toHaveBeenCalled();
    expect(api.getAutoTradeStatus).toHaveBeenCalled();
    expect(api.getSymbols).toHaveBeenCalled();
    expect(api.getAutoTradePresets).toHaveBeenCalled();
  });

  it("設定の取得に失敗した場合はエラー内容と再試行ボタンを表示する", async () => {
    mockApis();
    vi.spyOn(api, "getAutoTradeConfig").mockRejectedValue(new Error("読み込みに失敗しました"));

    render(<AutoTradePanel />);

    await waitFor(() => expect(screen.getByText("読み込みに失敗しました")).toBeTruthy());
    expect(screen.getByRole("button", { name: "再試行" })).toBeTruthy();
    // 設定が無いので操作 UI（エンジン設定など）は描画しない
    expect(screen.queryByRole("heading", { name: "エンジン設定" })).toBeNull();
  });

  it("エラーメッセージが取れない場合も汎用文言でフォールバックする", async () => {
    mockApis();
    // reject ではなく config を持たないレスポンスを返すケース
    vi.spyOn(api, "getAutoTradeConfig").mockResolvedValue({
      config: null,
      defaults: fixtures.autoTradeConfig(),
    } as unknown as Awaited<ReturnType<typeof api.getAutoTradeConfig>>);

    render(<AutoTradePanel />);

    await waitFor(() =>
      expect(screen.getByText("自動取引設定を取得できませんでした。")).toBeTruthy(),
    );
  });

  it("再試行ボタンで設定を取り直し、成功すれば通常画面に戻る", async () => {
    mockApis();
    const getConfig = vi
      .spyOn(api, "getAutoTradeConfig")
      .mockRejectedValueOnce(new Error("読み込みに失敗しました"))
      .mockResolvedValueOnce({
        config: fixtures.autoTradeConfig(),
        defaults: fixtures.autoTradeConfig(),
      });

    render(<AutoTradePanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "再試行" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "再試行" }));

    await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(2));
    await waitLoaded();
    expect(screen.queryByText("読み込みに失敗しました")).toBeNull();
  });

  it("更新ボタンで再取得する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "更新" }));

    await waitFor(() => expect(api.getAutoTradeConfig).toHaveBeenCalledTimes(2));
  });

  it("プリセット取得に失敗しても画面は描画される", async () => {
    mockApis();
    vi.spyOn(api, "getAutoTradePresets").mockRejectedValue(new Error("403"));

    render(<AutoTradePanel />);

    await waitLoaded();
    expect(document.querySelectorAll(".preset-card")).toHaveLength(0);
  });
});

describe("AutoTradePanel — プリセット", () => {
  it("プリセット一覧を表示し、現在の選択にクラスを付ける", async () => {
    mockApis({ config: { strategy_preset: "balanced" } });
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByText("バランス")).toBeTruthy();
    expect(screen.getByText("アグレッシブ")).toBeTruthy();
    expect(screen.getByText("バランス").closest("button")?.className).toContain("preset-active");
  });

  it("プリセットを選ぶと適用して再読み込みする", async () => {
    mockApis();
    const apply = vi
      .spyOn(api, "applyAutoTradePreset")
      .mockResolvedValue({ config: fixtures.autoTradeConfig({ strategy_preset: "aggressive" }) });

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByText("アグレッシブ").closest("button") as HTMLElement);

    await waitFor(() => expect(apply).toHaveBeenCalledWith("aggressive"));
    await waitFor(() => expect(api.getAutoTradeConfig).toHaveBeenCalledTimes(2));
  });

  it("プリセット適用に失敗した場合はエラーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "applyAutoTradePreset").mockRejectedValue(new Error("プリセット適用に失敗しました"));

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByText("アグレッシブ").closest("button") as HTMLElement);

    await waitFor(() => expect(screen.getByText("プリセット適用に失敗しました")).toBeTruthy());
  });
});

describe("AutoTradePanel — オートセレクト", () => {
  it("『提案を見る』では適用せず理由のみ表示する", async () => {
    mockApis();
    const autoselect = vi.spyOn(api, "autoSelectAutoTrade").mockResolvedValue({
      recommended_preset: "balanced",
      preset_label: "バランス",
      config: fixtures.autoTradeConfig(),
      rationale: "中期・標準リスクにはバランス型が適します。",
    });

    render(<AutoTradePanel />);
    await waitLoaded();
    const callsBefore = vi.mocked(api.getAutoTradeConfig).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "提案を見る" }));

    await waitFor(() =>
      expect(autoselect).toHaveBeenCalledWith({
        capital: "medium",
        horizon: "medium",
        risk_appetite: "medium",
        apply: false,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText("中期・標準リスクにはバランス型が適します。")).toBeTruthy(),
    );
    expect(vi.mocked(api.getAutoTradeConfig).mock.calls.length).toBe(callsBefore);
  });

  it("『適用して保存』では apply: true で呼び再読み込みする", async () => {
    mockApis();
    const autoselect = vi.spyOn(api, "autoSelectAutoTrade").mockResolvedValue({
      recommended_preset: "aggressive",
      preset_label: "アグレッシブ",
      config: fixtures.autoTradeConfig({ strategy_preset: "aggressive" }),
      rationale: "高リスク許容のため",
    });

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "適用して保存" }));

    await waitFor(() =>
      expect(autoselect).toHaveBeenCalledWith(expect.objectContaining({ apply: true })),
    );
    await waitFor(() => expect(api.getAutoTradeConfig).toHaveBeenCalledTimes(2));
  });

  it("3 問の回答を API に反映する", async () => {
    mockApis();
    const autoselect = vi.spyOn(api, "autoSelectAutoTrade").mockResolvedValue({
      recommended_preset: "conservative",
      preset_label: "保守",
      config: fixtures.autoTradeConfig(),
      rationale: "小額・短期・低リスク",
    });

    render(<AutoTradePanel />);
    await waitLoaded();
    const selects = Array.from(document.querySelectorAll(".form-grid select"));
    fireEvent.change(selects[0], { target: { value: "small" } });
    fireEvent.change(selects[1], { target: { value: "short" } });
    fireEvent.change(selects[2], { target: { value: "low" } });
    fireEvent.click(screen.getByRole("button", { name: "提案を見る" }));

    await waitFor(() =>
      expect(autoselect).toHaveBeenCalledWith({
        capital: "small",
        horizon: "short",
        risk_appetite: "low",
        apply: false,
      }),
    );
  });
});

describe("AutoTradePanel — シミュレーション", () => {
  it("設定の残高とプリセットでシミュレーションを実行する", async () => {
    mockApis({ config: { account_balance: 25000, strategy_preset: "aggressive" } });
    const sim = vi
      .spyOn(api, "simulateAutoTrade")
      .mockResolvedValue(fixtures.autoTradeSimulation());

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "シミュレーション実行" }));

    await waitFor(() =>
      expect(sim).toHaveBeenCalledWith("USDJPY", {
        accountBalance: 25000,
        presetId: "aggressive",
      }),
    );
  });

  it("実行中は進捗メッセージを表示する", async () => {
    mockApis();
    vi.spyOn(api, "simulateAutoTrade").mockReturnValue(new Promise(() => {}));

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "シミュレーション実行" }));

    expect(screen.getByText("⏳ 計算中...")).toBeTruthy();
    expect(screen.getByText(/365 日分のデータでバックテスト/)).toBeTruthy();
  });

  it("結果のグレード・勝率・証拠金・運用可否を表示する", async () => {
    mockApis();
    vi.spyOn(api, "simulateAutoTrade").mockResolvedValue(fixtures.autoTradeSimulation());

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "シミュレーション実行" }));

    await waitFor(() => expect(screen.getByText("B")).toBeTruthy());
    expect(screen.getByText("58.3%")).toBeTruthy();
    expect(screen.getByText("24回")).toBeTruthy();
    expect(screen.getByText("$12,000")).toBeTruthy();
    expect(screen.getByText("$20,000")).toBeTruthy();
    expect(screen.getByText("✓ 可")).toBeTruthy();
    expect(screen.getByText("実運用可能な水準です。")).toBeTruthy();
  });

  it("運用不可の判定は『要検討』と表示する", async () => {
    mockApis();
    vi.spyOn(api, "simulateAutoTrade").mockResolvedValue(
      fixtures.autoTradeSimulation({
        assessment: { grade: "D", ready_to_deploy: false, summary: "証拠金が不足しています。" },
      }),
    );

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "シミュレーション実行" }));

    await waitFor(() => expect(screen.getByText("要検討")).toBeTruthy());
  });

  it("失敗時は専用のエラー表示を出す", async () => {
    mockApis();
    vi.spyOn(api, "simulateAutoTrade").mockRejectedValue(new Error("データ不足です"));

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "シミュレーション実行" }));

    await waitFor(() => expect(screen.getByText("⚠ データ不足です")).toBeTruthy());
  });
});

describe("AutoTradePanel — 評価と実行", () => {
  it("ドライラン評価は確認なしで実行し結果を表示する", async () => {
    mockApis();
    const evaluate = vi
      .spyOn(api, "evaluateAutoTrade")
      .mockResolvedValue(fixtures.autoTradeEvaluation());
    const confirm = vi.spyOn(window, "confirm");

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "ドライラン評価" }));

    await waitFor(() => expect(evaluate).toHaveBeenCalledWith("USDJPY"));
    expect(confirm).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("評価結果 — USDJPY")).toBeTruthy());
    expect(screen.getByText("実行可能")).toBeTruthy();
    expect(screen.getByText("全条件を満たしています")).toBeTruthy();
    expect(screen.getByText(/推奨: buy 1000 units/)).toBeTruthy();
  });

  it("単一シンボル実行は確認ダイアログを経てから実行する", async () => {
    mockApis({ config: { enabled: true } });
    const run = vi.spyOn(api, "runAutoTradeSymbol").mockResolvedValue(fixtures.autoTradeEvaluation());
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "USDJPY を実行" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("USDJPY で自動取引を実行"));
    await waitFor(() => expect(run).toHaveBeenCalledWith("USDJPY"));
  });

  it("確認ダイアログをキャンセルすると実行しない", async () => {
    mockApis({ config: { enabled: true } });
    const run = vi.spyOn(api, "runAutoTradeSymbol");
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "USDJPY を実行" }));

    expect(run).not.toHaveBeenCalled();
  });

  it("全シンボル実行も確認ダイアログを経てから実行する", async () => {
    mockApis({ config: { enabled: true } });
    const runAll = vi.spyOn(api, "runAutoTradeAll").mockResolvedValue({
      results: [],
    } as unknown as Awaited<ReturnType<typeof api.runAutoTradeAll>>);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "全シンボル実行" }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("監視中の全シンボル"));
    await waitFor(() => expect(runAll).toHaveBeenCalled());
  });

  it("全シンボル実行をキャンセルすると実行しない", async () => {
    mockApis({ config: { enabled: true } });
    const runAll = vi.spyOn(api, "runAutoTradeAll");
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "全シンボル実行" }));

    expect(runAll).not.toHaveBeenCalled();
  });

  it("自動取引が無効なときは実行ボタンを非活性化する", async () => {
    mockApis({ config: { enabled: false } });

    render(<AutoTradePanel />);
    await waitLoaded();

    expect(
      (screen.getByRole("button", { name: "USDJPY を実行" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "全シンボル実行" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    // ドライランは無効時でも使える
    expect(
      (screen.getByRole("button", { name: "ドライラン評価" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("評価に失敗した場合はエラーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "evaluateAutoTrade").mockRejectedValue(new Error("評価に失敗しました"));

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "ドライラン評価" }));

    await waitFor(() => expect(screen.getByText("評価に失敗しました")).toBeTruthy());
  });

  it("判定に応じて色クラスを切り替える", async () => {
    mockApis();
    vi.spyOn(api, "evaluateAutoTrade").mockResolvedValue(
      fixtures.autoTradeEvaluation({ decision: "blocked", reason: "信頼度不足" }),
    );

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "ドライラン評価" }));

    await waitFor(() => expect(screen.getByText("ブロック")).toBeTruthy());
    expect(screen.getByText("ブロック").className).toContain("text-sell");
  });
});

describe("AutoTradePanel — 設定変更", () => {
  it("有効化チェックボックスは即時保存する", async () => {
    mockApis({ config: { enabled: false } });
    const update = vi
      .spyOn(api, "updateAutoTradeConfig")
      .mockResolvedValue({ config: fixtures.autoTradeConfig({ enabled: true }) });

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(checkbox("自動取引を有効化"));

    await waitFor(() => expect(update).toHaveBeenCalledWith({ enabled: true }));
  });

  it("数値入力は変更時には保存せず、フォーカスが外れたときに保存する", async () => {
    mockApis();
    const update = vi
      .spyOn(api, "updateAutoTradeConfig")
      .mockResolvedValue({ config: fixtures.autoTradeConfig({ min_confidence: 80 }) });

    render(<AutoTradePanel />);
    await waitLoaded();
    const input = numberInput("最低信頼度");

    fireEvent.change(input, { target: { value: "80" } });
    expect(update).not.toHaveBeenCalled();

    fireEvent.blur(input);

    await waitFor(() => expect(update).toHaveBeenCalledWith({ min_confidence: 80 }));
  });

  it("各種チェックボックスが対応するフィールドを保存する", async () => {
    mockApis();
    const update = vi
      .spyOn(api, "updateAutoTradeConfig")
      .mockResolvedValue({ config: fixtures.autoTradeConfig() });

    render(<AutoTradePanel />);
    await waitLoaded();

    fireEvent.click(checkbox("MTF 方向一致を必須"));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ require_mtf_alignment: true }));

    fireEvent.click(checkbox("損切り (SL) を自動設定"));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ use_stop_loss: false }));
  });

  it("保存に失敗した場合はエラーを表示する", async () => {
    mockApis();
    vi.spyOn(api, "updateAutoTradeConfig").mockRejectedValue(new Error("保存に失敗しました"));

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(checkbox("自動取引を有効化"));

    await waitFor(() => expect(screen.getByText("保存に失敗しました")).toBeTruthy());
  });
});

describe("AutoTradePanel — チップ（通貨ペア・シグナルソース）", () => {
  /** チップ要素を取得する */
  function chip(label: string): HTMLElement {
    const el = Array.from(document.querySelectorAll(".chip")).find(
      (n) => n.textContent === label,
    );
    if (!el) throw new Error(`チップが見つかりません: ${label}`);
    return el as HTMLElement;
  }

  it("設定に含まれる通貨ペアをアクティブ表示する", async () => {
    mockApis({ config: { symbols: ["USDJPY"] } });
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(chip("USDJPY").className).toContain("chip-active");
    expect(chip("EURUSD").className).not.toContain("chip-active");
  });

  it("未選択の通貨ペアをクリックすると追加保存する", async () => {
    mockApis({ config: { symbols: ["USDJPY"] } });
    const update = vi
      .spyOn(api, "updateAutoTradeConfig")
      .mockResolvedValue({ config: fixtures.autoTradeConfig() });

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(chip("EURUSD"));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({ symbols: ["USDJPY", "EURUSD"] }),
    );
  });

  it("最後の 1 つの通貨ペアは外せない", async () => {
    mockApis({ config: { symbols: ["USDJPY"] } });
    const update = vi.spyOn(api, "updateAutoTradeConfig");

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(chip("USDJPY"));

    expect(update).not.toHaveBeenCalled();
  });

  it("シグナルソースを追加・削除できる", async () => {
    mockApis({ config: { sources: ["ai", "technical"] } });
    const update = vi
      .spyOn(api, "updateAutoTradeConfig")
      .mockResolvedValue({ config: fixtures.autoTradeConfig() });

    render(<AutoTradePanel />);
    await waitLoaded();

    fireEvent.click(chip("テクニカル"));
    await waitFor(() => expect(update).toHaveBeenCalledWith({ sources: ["ai"] }));

    fireEvent.click(chip("TradingView"));
    await waitFor(() =>
      expect(update).toHaveBeenLastCalledWith({ sources: ["ai", "technical", "tradingview"] }),
    );
  });

  it("最後の 1 つのシグナルソースは外せない", async () => {
    mockApis({ config: { sources: ["ai"] } });
    const update = vi.spyOn(api, "updateAutoTradeConfig");

    render(<AutoTradePanel />);
    await waitLoaded();
    fireEvent.click(chip("AI シグナル"));

    expect(update).not.toHaveBeenCalled();
  });
});

describe("AutoTradePanel — 状況表示", () => {
  it("パフォーマンス指標を表示する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getAllByText("42.5%").length).toBeGreaterThan(0);
    expect(screen.getByText("17 / 23")).toBeTruthy();
    expect(screen.getByText("66.1%")).toBeTruthy();
    expect(screen.getByText("61.5% (13件)")).toBeTruthy();
    expect(screen.getByText("週次実現損益")).toBeTruthy();
    expect(screen.getByText("週次で設定を見直してください。")).toBeTruthy();
  });

  it("分散ロックのバックエンドを表示する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByText("Redis")).toBeTruthy();
  });

  it("スケジューラの状態・モード・間隔を表示する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByText("有効 · 稼働中")).toBeTruthy();
    expect(screen.getByText("15 分")).toBeTruthy();
  });

  it("オープンポジションを一覧表示する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByRole("heading", { name: "オープンポジション" })).toBeTruthy();
    expect(screen.getByText("151.2")).toBeTruthy();
    expect(screen.getByText("150.5")).toBeTruthy();
  });

  it("オープンポジションが無い場合はセクションを出さない", async () => {
    mockApis({ status: { open_positions: [] } });
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.queryByRole("heading", { name: "オープンポジション" })).toBeNull();
  });

  it("実行ログを表示する", async () => {
    mockApis();
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByRole("heading", { name: "実行ログ" })).toBeTruthy();
    expect(screen.getAllByText("AI シグナルが閾値を超過").length).toBeGreaterThan(0);
    expect(screen.getAllByText("約定").length).toBeGreaterThan(0);
  });

  it("実行ログが無い場合は案内を表示する", async () => {
    mockApis({ status: { recent_runs: [] } });
    render(<AutoTradePanel />);
    await waitLoaded();

    expect(screen.getByText(/実行ログはまだありません/)).toBeTruthy();
  });
});
