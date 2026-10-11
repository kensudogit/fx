/**
 * @file types/index.test.ts
 * @description `src/types/index.ts`（API レスポンス型定義）の型契約テスト。
 *
 * このモジュールは実行時コードを一切持たない型定義専用ファイルのため、
 * 「型が期待どおりに使えること」を次の 2 段構えで検証する。
 *
 * 1. 静的検証 — `satisfies` を用いたリテラルで必須・任意プロパティを固定する。
 *    型定義が変更されると `npm run build` / `tsc --noEmit` がここで失敗する。
 * 2. 実行時検証 — `expectTypeOf` による型アサーションと、
 *    フィクスチャが実際に型どおりの値を返すことの確認。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, expectTypeOf } from "vitest";
import type {
  AutoTradeConfig,
  CalendarEvent,
  ChatMessage,
  ChatResponse,
  OHLCV,
  SignalBacktest,
  TechnicalAnalysis,
  TradingSignal,
} from "./index";
import * as fixtures from "@/test/fixtures";

describe("types — OHLCV", () => {
  it("6 項目すべてを必須とする", () => {
    const bar = {
      timestamp: "2026-01-02",
      open: 150.0,
      high: 151.0,
      low: 149.5,
      close: 150.5,
      volume: 1200,
    } satisfies OHLCV;

    expect(Object.keys(bar)).toHaveLength(6);
    expectTypeOf(bar.close).toBeNumber();
    expectTypeOf(bar.timestamp).toBeString();
  });
});

describe("types — TradingSignal", () => {
  it("signal は buy / sell のリテラル union", () => {
    const buy = { indicator: "RSI", signal: "buy", reason: "売られすぎ" } satisfies TradingSignal;
    const sell = { indicator: "MACD", signal: "sell", reason: "デッドクロス" } satisfies TradingSignal;

    expect([buy.signal, sell.signal]).toEqual(["buy", "sell"]);
    expectTypeOf<TradingSignal["signal"]>().toEqualTypeOf<"buy" | "sell">();
  });

  it("value は任意項目（指標値を持たないシグナルも表現できる）", () => {
    const withoutValue: TradingSignal = {
      indicator: "一目均衡表",
      signal: "buy",
      reason: "雲抜け",
    } satisfies TradingSignal;

    expect(withoutValue.value).toBeUndefined();
    expectTypeOf<TradingSignal["value"]>().toEqualTypeOf<number | undefined>();
  });
});

describe("types — TechnicalAnalysis", () => {
  it("OHLCV・指標が時系列の配列として揃っている", () => {
    const data: TechnicalAnalysis = fixtures.technicalAnalysis();

    expect(data.timestamps).toHaveLength(data.ohlcv.close.length);
    expect(data.indicators.ma.sma_20).toHaveLength(data.timestamps.length);
    expect(data.indicators.rsi).toHaveLength(data.timestamps.length);
    expectTypeOf(data.indicators.macd.histogram).toEqualTypeOf<(number | null)[]>();
  });

  it("latest は直近の代表値をまとめて持つ", () => {
    const data = fixtures.technicalAnalysis();
    expect(data.latest.close).toBe(151.5);
    expect(data.latest.rsi).toBeCloseTo(61.72, 2);
  });
});

describe("types — CalendarEvent", () => {
  it("日付・種別・タイトル・国・影響度を必須とする", () => {
    const event = {
      date: "2026-01-05",
      event_type: "fomc",
      title: "FOMC 政策金利発表",
      country: "US",
      impact: "high",
    } satisfies CalendarEvent;

    expect(event.impact).toBe("high");
    expectTypeOf(event).toMatchTypeOf<CalendarEvent>();
  });
});

describe("types — SignalBacktest", () => {
  it("勝率・取引数などの集計値を必須、source / message を任意とする", () => {
    const minimal: SignalBacktest = {
      symbol: "USDJPY",
      total_trades: 0,
      win_rate: 0,
      avg_return_pct: 0,
      buy_trades: 0,
      sell_trades: 0,
    } satisfies SignalBacktest;

    expect(minimal.source).toBeUndefined();
    expect(minimal.message).toBeUndefined();
  });
});

describe("types — チャット関連", () => {
  it("ChatMessage は role / content を必須とする", () => {
    const msg: ChatMessage = { role: "user", content: "今週の戦略は？" } satisfies ChatMessage;
    expect(msg.created_at).toBeUndefined();
  });

  it("ChatResponse は messages を省略できる（reply のみの応答も許容）", () => {
    const res: ChatResponse = {
      session_id: 1,
      symbol: "USDJPY",
      reply: "押し目買いを推奨します。",
    } satisfies ChatResponse;

    expect(res.messages).toBeUndefined();
    expectTypeOf<ChatResponse["messages"]>().toEqualTypeOf<ChatMessage[] | undefined>();
  });
});

describe("types — AutoTradeConfig", () => {
  it("フィクスチャが自動取引パネルの参照する項目をすべて備える", () => {
    const config: AutoTradeConfig = fixtures.autoTradeConfig();

    for (const key of [
      "enabled",
      "min_confidence",
      "risk_percent",
      "account_balance",
      "max_daily_trades",
      "cooldown_minutes",
      "event_blackout_hours",
      "symbols",
      "sources",
      "require_mtf_alignment",
      "auto_execute_tradingview",
    ]) {
      expect(config).toHaveProperty(key);
    }
  });

  it("symbols / sources は文字列配列", () => {
    const config = fixtures.autoTradeConfig();
    expectTypeOf(config.symbols).toEqualTypeOf<string[]>();
    expectTypeOf(config.sources).toEqualTypeOf<string[]>();
  });
});

describe("types — モジュールの性質", () => {
  it("実行時の値をエクスポートしない（純粋な型定義モジュール）", async () => {
    const mod = await import("./index");
    // 型のみのモジュールはランタイムでは空オブジェクトになる
    expect(Object.keys(mod).filter((k) => k !== "default")).toHaveLength(0);
  });
});
