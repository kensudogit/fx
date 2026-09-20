/**
 * @file Chart.test.tsx
 * @description `PriceChart` / `OscillatorChart`（recharts ベースの描画）のユニットテスト。
 *
 * recharts の ResponsiveContainer は jsdom では寸法 0 になり子要素を描画しないため、
 * recharts 全体をモックし「どの系列を、どのデータで描こうとしたか」を検証する。
 *
 * 検証範囲:
 * - TechnicalAnalysis から組み立てられるチャートデータ（日付整形・指標の対応付け）
 * - showMA / showBB / showIchimoku による系列の出し分け
 * - OscillatorChart の type（rsi / macd / stochastic）ごとのチャート種別と系列
 * - RSI・ストキャスティクスの参照線と Y 軸レンジ
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PriceChart, { OscillatorChart } from "./Chart";
import { technicalAnalysis } from "@/test/fixtures";

/**
 * recharts を軽量な DOM 要素へ差し替える。
 * - チャート本体は `data-chart` 属性に種別、`data-rows` に行数を出す。
 * - 系列（Line / Bar / Area）は `data-series` 属性に dataKey を出す。
 * - チャートに渡された生データは `chartData` に記録して検証に使う。
 */
const chartData: { current: Record<string, unknown>[] } = { current: [] };

vi.mock("recharts", () => {
  const Container = (name: string) =>
    function Chart({ data, children }: { data: Record<string, unknown>[]; children: React.ReactNode }) {
      chartData.current = data;
      return (
        <div data-testid="chart" data-chart={name} data-rows={data.length}>
          {children}
        </div>
      );
    };
  const Series = (name: string) =>
    function SeriesMark({ dataKey }: { dataKey?: string }) {
      return <span data-testid="series" data-series={dataKey} data-mark={name} />;
    };
  const Passthrough = (name: string) =>
    function Element({ y }: { y?: number }) {
      return <span data-testid={name} data-y={y} />;
    };

  return {
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    ComposedChart: Container("composed"),
    LineChart: Container("line"),
    Line: Series("line"),
    Bar: Series("bar"),
    Area: Series("area"),
    CartesianGrid: Passthrough("grid"),
    Tooltip: Passthrough("tooltip"),
    ReferenceLine: Passthrough("reference-line"),
    XAxis: function XAxis({ dataKey }: { dataKey?: string }) {
      return <span data-testid="x-axis" data-key={dataKey} />;
    },
    YAxis: function YAxis({ domain }: { domain?: unknown[] }) {
      return <span data-testid="y-axis" data-domain={JSON.stringify(domain)} />;
    },
  };
});

/** 描画された系列の dataKey 一覧を返す */
function seriesKeys(): string[] {
  return screen
    .queryAllByTestId("series")
    .map((el) => el.getAttribute("data-series") ?? "")
    .filter(Boolean);
}

describe("PriceChart — チャートデータの組み立て", () => {
  it("timestamps の件数だけ行を作る", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(screen.getByTestId("chart").getAttribute("data-rows")).toBe("3");
  });

  it("日付を MM-DD 形式（先頭 5〜10 文字）に整形する", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(chartData.current.map((r) => r.date)).toEqual(["01-01", "01-02", "01-03"]);
  });

  it("終値・移動平均・ボリンジャー・一目の値を同じ行に対応付ける", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(chartData.current[2]).toMatchObject({
      close: 151.5,
      sma20: 151.1,
      sma50: 150.8,
      bbUpper: 153.0,
      bbMiddle: 151.2,
      bbLower: 149.4,
      tenkan: 151.2,
      kijun: 150.9,
      senkouA: 151.0,
      senkouB: 150.6,
    });
  });

  it("X 軸は date、Y 軸は auto レンジを使う", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(screen.getByTestId("x-axis").getAttribute("data-key")).toBe("date");
    expect(screen.getByTestId("y-axis").getAttribute("data-domain")).toBe('["auto","auto"]');
  });

  it("空データでも例外なく描画できる", () => {
    const empty = technicalAnalysis({ timestamps: [] });
    render(<PriceChart data={empty} />);
    expect(screen.getByTestId("chart").getAttribute("data-rows")).toBe("0");
  });
});

describe("PriceChart — 系列の出し分け", () => {
  it("既定（showMA）では終値と SMA20 / SMA50 を描く", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(seriesKeys()).toEqual(["close", "sma20", "sma50"]);
  });

  it("showMA=false では終値のみ描く", () => {
    render(<PriceChart data={technicalAnalysis()} showMA={false} />);
    expect(seriesKeys()).toEqual(["close"]);
  });

  it("showBB でボリンジャーバンドの 4 系列（塗り + 上中下）を追加する", () => {
    render(<PriceChart data={technicalAnalysis()} showMA={false} showBB />);
    expect(seriesKeys()).toEqual(["bbUpper", "bbUpper", "bbMiddle", "bbLower", "close"]);
  });

  it("showIchimoku で転換・基準・先行スパン A/B を追加する", () => {
    render(<PriceChart data={technicalAnalysis()} showMA={false} showIchimoku />);
    expect(seriesKeys()).toEqual(["tenkan", "kijun", "senkouA", "senkouB", "close"]);
  });

  it("複合チャート（ComposedChart）で描画する", () => {
    render(<PriceChart data={technicalAnalysis()} />);
    expect(screen.getByTestId("chart").getAttribute("data-chart")).toBe("composed");
  });
});

describe("OscillatorChart — RSI", () => {
  it("rsi 系列を LineChart で描画する", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="rsi" />);
    expect(screen.getByTestId("chart").getAttribute("data-chart")).toBe("line");
    expect(seriesKeys()).toEqual(["rsi"]);
  });

  it("Y 軸を 0〜100 に固定する", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="rsi" />);
    expect(screen.getByTestId("y-axis").getAttribute("data-domain")).toBe("[0,100]");
  });

  it("買われすぎ 70 / 売られすぎ 30 の参照線を引く", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="rsi" />);
    const lines = screen.getAllByTestId("reference-line").map((el) => el.getAttribute("data-y"));
    expect(lines).toEqual(["70", "30"]);
  });
});

describe("OscillatorChart — MACD", () => {
  it("ヒストグラム（Bar）と MACD / シグナル（Line）を描画する", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="macd" />);
    expect(seriesKeys()).toEqual(["histogram", "macd", "signal"]);
    expect(screen.getByTestId("chart").getAttribute("data-chart")).toBe("composed");
  });

  it("参照線は引かない", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="macd" />);
    expect(screen.queryAllByTestId("reference-line")).toHaveLength(0);
  });
});

describe("OscillatorChart — ストキャスティクス", () => {
  it("%K / %D の 2 系列を描画する", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="stochastic" />);
    expect(seriesKeys()).toEqual(["stochK", "stochD"]);
  });

  it("80 / 20 の参照線を引く", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="stochastic" />);
    const lines = screen.getAllByTestId("reference-line").map((el) => el.getAttribute("data-y"));
    expect(lines).toEqual(["80", "20"]);
  });

  it("オシレーターのデータ行に rsi / macd / stochastic の値が揃う", () => {
    render(<OscillatorChart data={technicalAnalysis()} type="stochastic" />);
    expect(chartData.current[0]).toMatchObject({
      date: "01-01",
      rsi: 45.1,
      macd: 0.1,
      signal: 0.05,
      histogram: 0.05,
      stochK: 40,
      stochD: 42,
    });
  });
});
