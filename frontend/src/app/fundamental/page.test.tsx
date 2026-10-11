/**
 * @file fundamental/page.test.tsx
 * @description `FundamentalPage`（/fundamental）のユニットテスト。
 *
 * 検証範囲:
 * - 初期ロード（経済指標とカレンダーの並列取得）とローディング表示
 * - 取得失敗時の挙動
 * - イベント種別タブの切り替えと active クラス
 * - データソース表記（FRED / サンプルデータ）
 * - 指標テーブル（欠損値のダッシュ表示）
 * - カレンダーの残り日数バッジ（本日 / 3 日以内 / それ以降）と影響度の表記
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import FundamentalPage from "./page";
import * as api from "@/lib/api";
import { calendarEvent, fundamentalData } from "@/test/fixtures";
import { flush } from "@/test/utils";
import type { CalendarEvent, FundamentalData } from "@/types";

/** 「現在」を固定して残り日数の計算を決定的にする */
function freezeNow(iso = "2026-01-01T00:00:00Z") {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(iso));
}

/** API をモックする */
function mockApis(data?: Partial<FundamentalData>, events: CalendarEvent[] = []) {
  vi.spyOn(api, "getFundamentalData").mockResolvedValue(fundamentalData(data));
  vi.spyOn(api, "getCalendar").mockResolvedValue({ events });
}

/** 読み込み完了を待つ */
async function waitLoaded() {
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "ファンダメンタル分析" })).toBeTruthy(),
  );
}

/**
 * フェイクタイマー下で読み込み完了を待つ。
 * `waitFor` は実時間のタイマーに依存するため、
 * 日付を固定するテストではマイクロタスクを直接消化する。
 */
async function waitLoadedFrozen() {
  await flush();
  expect(screen.getByRole("heading", { name: "ファンダメンタル分析" })).toBeTruthy();
}

afterEach(() => {
  vi.useRealTimers();
});

describe("FundamentalPage — ロード", () => {
  it("読み込み中は専用メッセージを表示する", () => {
    mockApis();
    vi.spyOn(api, "getFundamentalData").mockReturnValue(new Promise(() => {}));

    render(<FundamentalPage />);

    expect(screen.getByText("データを読み込み中...")).toBeTruthy();
  });

  it("指標とカレンダーを取得する", async () => {
    mockApis();
    render(<FundamentalPage />);
    await waitLoaded();

    expect(api.getFundamentalData).toHaveBeenCalled();
    expect(api.getCalendar).toHaveBeenCalled();
  });

  it("取得に失敗した場合はローディングのまま停止する", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(api, "getFundamentalData").mockRejectedValue(new Error("500"));
    vi.spyOn(api, "getCalendar").mockResolvedValue({ events: [] });

    render(<FundamentalPage />);

    // data が null のままなのでローディング表示が残る（現仕様）
    await waitFor(() => expect(screen.getByText("データを読み込み中...")).toBeTruthy());
  });
});

describe("FundamentalPage — 経済指標タブ", () => {
  it("5 種類のタブを表示し、初期は米国雇用統計を選択する", async () => {
    mockApis();
    render(<FundamentalPage />);
    await waitLoaded();

    for (const label of ["米国雇用統計", "CPI", "FOMC", "日銀政策決定会合", "GDP"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
    expect(screen.getByRole("button", { name: "米国雇用統計" }).className).toContain("active");
  });

  it("タブを切り替えると対応するデータを表示する", async () => {
    mockApis();
    render(<FundamentalPage />);
    await waitLoaded();
    expect(screen.getByText("データソース: FRED API")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "CPI" }));

    expect(screen.getByText("データソース: サンプルデータ")).toBeTruthy();
    expect(screen.getByRole("button", { name: "CPI" }).className).toContain("active");
  });

  it("選択したタブのデータが無い場合はテーブルを描画しない", async () => {
    mockApis();
    render(<FundamentalPage />);
    await waitLoaded();

    fireEvent.click(screen.getByRole("button", { name: "FOMC" }));

    expect(screen.queryByText(/データソース:/)).toBeNull();
  });

  it("実績・予想・前回・単位を表示し、欠損はダッシュにする", async () => {
    mockApis();
    const { container } = render(<FundamentalPage />);
    await waitLoaded();

    const rows = container.querySelectorAll("tbody tr");
    expect(Array.from(rows[0].querySelectorAll("td")).map((td) => td.textContent)).toEqual([
      "2025-12-05",
      "210",
      "190",
      "180",
      "千人",
    ]);
    expect(Array.from(rows[1].querySelectorAll("td")).map((td) => td.textContent)).toEqual([
      "2025-11-07",
      "180",
      "-",
      "-",
      "-",
    ]);
  });
});

describe("FundamentalPage — カレンダー", () => {
  /** カレンダーテーブル（2 つ目のテーブル）の行を返す */
  function calendarRows(container: HTMLElement) {
    return container.querySelectorAll("table")[1].querySelectorAll("tbody tr");
  }

  it("当日以前のイベントは『本日』バッジを表示する", async () => {
    freezeNow();
    mockApis(undefined, [calendarEvent({ date: "2026-01-01", title: "本日のイベント" })]);

    const { container } = render(<FundamentalPage />);
    await waitLoadedFrozen();

    const badge = calendarRows(container)[0].querySelectorAll("td")[1];
    expect(badge.textContent).toBe("本日");
    expect(badge.querySelector(".badge-warn")).toBeTruthy();
  });

  it("3 日以内のイベントは警告バッジで日数を表示する", async () => {
    freezeNow();
    mockApis(undefined, [calendarEvent({ date: "2026-01-03", title: "3日後" })]);

    const { container } = render(<FundamentalPage />);
    await waitLoadedFrozen();

    const cell = calendarRows(container)[0].querySelectorAll("td")[1];
    expect(cell.textContent).toBe("2日");
    expect(cell.querySelector(".badge-warn")).toBeTruthy();
  });

  it("4 日以上先のイベントはバッジなしで日数のみ表示する", async () => {
    freezeNow();
    mockApis(undefined, [calendarEvent({ date: "2026-01-20", title: "先のイベント" })]);

    const { container } = render(<FundamentalPage />);
    await waitLoadedFrozen();

    const cell = calendarRows(container)[0].querySelectorAll("td")[1];
    expect(cell.textContent).toBe("19日");
    expect(cell.querySelector(".badge")).toBeNull();
  });

  it("イベント名・国・影響度を表示する", async () => {
    freezeNow();
    mockApis(undefined, [
      calendarEvent({ date: "2026-01-10", title: "米連邦公開市場委員会", country: "US", impact: "high" }),
      calendarEvent({ date: "2026-01-12", title: "日銀会合", country: "JP", impact: "medium" }),
    ]);

    const { container } = render(<FundamentalPage />);
    await waitLoadedFrozen();

    expect(screen.getByText("米連邦公開市場委員会")).toBeTruthy();
    expect(screen.getByText("JP")).toBeTruthy();
    expect(container.querySelector("td.impact-high")?.textContent).toBe("高");
    expect(container.querySelector("td.impact-medium")?.textContent).toBe("中");
  });

  it("イベントが無い場合でもテーブルの見出しは表示する", async () => {
    mockApis(undefined, []);

    const { container } = render(<FundamentalPage />);
    await waitLoadedFrozen();

    expect(screen.getByRole("heading", { name: "経済イベントカレンダー" })).toBeTruthy();
    expect(calendarRows(container)).toHaveLength(0);
  });
});
