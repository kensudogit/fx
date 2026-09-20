/**
 * @file UsageGuidePanel.test.tsx
 * @description `UsageGuidePanel`（ドラッグ可能な利用手順パネル）のユニットテスト。
 *
 * 検証範囲:
 * - 初期化（localStorage 未保存 / 保存済み / 壊れた JSON）
 * - デスクトップ・モバイルでの初期位置と初期開閉状態
 * - 開閉トグルと aria 属性、状態の localStorage 永続化
 * - ヘッダードラッグによる移動と画面内へのクランプ、モバイルでの無効化
 * - トグルボタン上での pointerdown ではドラッグを開始しないこと
 * - リサイズ時の再クランプ
 * - 展開時の本文（ヒーロー・技術スタック・注目セクション・手順リスト）
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { UsageGuidePanel } from "./UsageGuidePanel";

/** localStorage の保存キー（実装と同じ値） */
const STORAGE_KEY = "fx-tool-usage-guide-v4";

/** ウィンドウサイズを設定する */
function setViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    writable: true,
    value: height,
  });
}

/** パネル本体の要素を返す */
function panel(): HTMLElement {
  return screen.getByRole("dialog", { name: "利用手順" });
}

/** 保存された状態を読み出す */
function saved(): { x: number; y: number; expanded: boolean } | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? JSON.parse(raw) : null;
}

beforeEach(() => {
  // デスクトップ相当の広い画面を既定にする
  setViewport(1280, 800);
});

describe("UsageGuidePanel — 初期化", () => {
  it("保存状態が無ければ画面右下に配置し展開状態で描画する", () => {
    render(<UsageGuidePanel />);

    const el = panel();
    // 右端から PANEL_WIDTH(440) + 24 の位置
    expect(el.style.left).toBe("816px");
    expect(el.style.top).toBe("280px");
    expect(el.style.width).toBe("440px");
    expect(el.className).toContain("is-expanded");
  });

  it("保存済みの位置・開閉状態を復元する", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 100, y: 200, expanded: false }));

    render(<UsageGuidePanel />);

    expect(panel().style.left).toBe("100px");
    expect(panel().style.top).toBe("200px");
    expect(panel().className).toContain("is-collapsed");
  });

  it("保存済みの位置が画面外なら画面内へクランプする", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 9999, y: 9999, expanded: true }));

    render(<UsageGuidePanel />);

    expect(panel().style.left).toBe("832px"); // 1280 - 440 - 8
    expect(panel().style.top).toBe("672px"); // 800 - 120 - 8
  });

  it("保存内容が壊れている場合は既定位置にフォールバックする", () => {
    localStorage.setItem(STORAGE_KEY, "{ 壊れた JSON");

    render(<UsageGuidePanel />);

    expect(panel().style.left).toBe("816px");
  });

  it("モバイル幅では折りたたみ状態で開始し、インラインスタイルを付けない", () => {
    setViewport(400, 800);

    render(<UsageGuidePanel />);

    expect(panel().className).toContain("is-mobile");
    expect(panel().className).toContain("is-collapsed");
    expect(panel().style.left).toBe("");
  });

  it("モバイルでは保存済みの expanded を無視して折りたたむ", () => {
    setViewport(400, 800);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ x: 10, y: 10, expanded: true }));

    render(<UsageGuidePanel />);

    expect(panel().className).toContain("is-collapsed");
  });
});

describe("UsageGuidePanel — 開閉", () => {
  it("トグルで開閉し aria-expanded とラベルを切り替える", () => {
    render(<UsageGuidePanel />);

    const toggle = screen.getByRole("button", { name: "閉じる" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(toggle);

    expect(panel().className).toContain("is-collapsed");
    const reopened = screen.getByRole("button", { name: "開く" });
    expect(reopened.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(reopened);
    expect(panel().className).toContain("is-expanded");
  });

  it("折りたたむと本文を描画しない", () => {
    render(<UsageGuidePanel />);
    expect(screen.getByText("FX 分析プラットフォーム")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByText("FX 分析プラットフォーム")).toBeNull();
  });

  it("開閉状態を localStorage に保存する", () => {
    render(<UsageGuidePanel />);
    expect(saved()?.expanded).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));

    expect(saved()?.expanded).toBe(false);
  });
});

describe("UsageGuidePanel — ドラッグ", () => {
  /** ヘッダー要素を返す */
  function header(): HTMLElement {
    return panel().querySelector(".usage-guide-header") as HTMLElement;
  }

  it("ヘッダーをドラッグするとパネルが移動する", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 900, clientY: 300 });
    expect(panel().className).toContain("is-dragging");

    fireEvent.pointerMove(header(), { pointerId: 1, clientX: 800, clientY: 250 });

    expect(panel().style.left).toBe("716px"); // 816 - 100
    expect(panel().style.top).toBe("230px"); // 280 - 50
  });

  it("pointerup でドラッグ状態を解除する", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 900, clientY: 300 });
    fireEvent.pointerUp(header(), { pointerId: 1 });

    expect(panel().className).not.toContain("is-dragging");
  });

  it("ドラッグ中でも画面外へは出さない", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 900, clientY: 300 });
    fireEvent.pointerMove(header(), { pointerId: 1, clientX: -5000, clientY: -5000 });

    expect(panel().style.left).toBe("8px");
    expect(panel().style.top).toBe("8px");
  });

  it("別の pointerId の move は無視する", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 900, clientY: 300 });
    fireEvent.pointerMove(header(), { pointerId: 2, clientX: 700, clientY: 100 });

    expect(panel().style.left).toBe("816px");
  });

  it("pointerdown していないときの move は無視する", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerMove(header(), { pointerId: 1, clientX: 700, clientY: 100 });

    expect(panel().style.left).toBe("816px");
  });

  it("トグルボタン上での pointerdown ではドラッグを開始しない", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "閉じる" }), {
      pointerId: 1,
      clientX: 900,
      clientY: 300,
    });

    expect(panel().className).not.toContain("is-dragging");
  });

  it("モバイルではドラッグを開始しない", () => {
    setViewport(400, 800);
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 100, clientY: 300 });

    expect(panel().className).not.toContain("is-dragging");
  });

  it("移動後の位置を localStorage に保存する", () => {
    render(<UsageGuidePanel />);

    fireEvent.pointerDown(header(), { pointerId: 1, clientX: 900, clientY: 300 });
    fireEvent.pointerMove(header(), { pointerId: 1, clientX: 800, clientY: 250 });

    expect(saved()).toMatchObject({ x: 716, y: 230 });
  });
});

describe("UsageGuidePanel — リサイズ", () => {
  it("ウィンドウが小さくなると位置を画面内へ再クランプする", () => {
    render(<UsageGuidePanel />);

    act(() => {
      setViewport(900, 600);
      window.dispatchEvent(new Event("resize"));
    });

    // jsdom では offsetWidth/offsetHeight が 0 のため、右下端（幅 8px マージン）へ寄る
    expect(Number(panel().style.left.replace("px", ""))).toBeLessThanOrEqual(892);
    expect(Number(panel().style.top.replace("px", ""))).toBeLessThanOrEqual(592);
  });

  it("モバイル幅になったら is-mobile クラスを付ける", () => {
    render(<UsageGuidePanel />);
    expect(panel().className).not.toContain("is-mobile");

    act(() => {
      setViewport(400, 800);
      window.dispatchEvent(new Event("resize"));
    });

    expect(panel().className).toContain("is-mobile");
  });
});

describe("UsageGuidePanel — 本文", () => {
  it("ヘッダーにタイトル・サブタイトル・ドラッグヒントを表示する", () => {
    render(<UsageGuidePanel />);

    expect(screen.getByText("利用手順")).toBeTruthy();
    expect(screen.getByText("Architecture & Ops")).toBeTruthy();
    expect(screen.getByText("ドラッグで移動")).toBeTruthy();
  });

  it("ヒーロー部と技術スタックのピルを表示する", () => {
    const { container } = render(<UsageGuidePanel />);

    expect(screen.getByRole("heading", { name: "FX 分析プラットフォーム" })).toBeTruthy();
    expect(container.querySelectorAll(".usage-guide-stack-pill").length).toBeGreaterThan(0);
  });

  it("アーキテクチャ図と注目セクションを表示する", () => {
    const { container } = render(<UsageGuidePanel />);

    expect(screen.getByLabelText("Service topology")).toBeTruthy();
    // FeaturedSection は 10 ブロック定義されている
    expect(container.querySelectorAll(".usage-guide-featured")).toHaveLength(10);
  });

  it("注目セクションに variant 別のクラスを付ける", () => {
    const { container } = render(<UsageGuidePanel />);

    expect(container.querySelector(".usage-guide-featured--architecture")).toBeTruthy();
    expect(container.querySelector(".usage-guide-featured--ai")).toBeTruthy();
  });

  it("詳細利用手順のセクションと手順リストを表示する", () => {
    const { container } = render(<UsageGuidePanel />);

    expect(screen.getByRole("heading", { name: "詳細利用手順" })).toBeTruthy();
    expect(container.querySelectorAll(".usage-guide-section").length).toBeGreaterThan(0);
    expect(container.querySelectorAll(".usage-guide-steps li").length).toBeGreaterThan(0);
  });

  it("トラブルシュートや API リファレンスの項目を含む", () => {
    render(<UsageGuidePanel />);

    expect(screen.getByText("よくあるエラーと対処")).toBeTruthy();
    expect(screen.getByText("API エンドポイント（開発者向け）")).toBeTruthy();
    expect(screen.getByText("GET /api/symbols — 利用可能通貨ペア一覧")).toBeTruthy();
  });

  it("フッターに操作ヒントを表示する", () => {
    render(<UsageGuidePanel />);

    expect(screen.getByText(/表示状態は自動保存されます/)).toBeTruthy();
  });
});
