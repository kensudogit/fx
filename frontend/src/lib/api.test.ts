/**
 * @file api.test.ts
 * @description `src/lib/api.ts`（バックエンド API クライアント）のユニットテスト。
 *
 * 検証範囲:
 * - fetchAPI の共通挙動（cache: no-store・認証ヘッダー付与・JSON パース）
 * - HTTP ステータスごとのエラーメッセージ変換（401 / 403 / 429 / 502 / 504 / その他）
 * - 401 時の自動ログアウトとログイン画面へのリダイレクト
 * - 各エンドポイントラッパーのパス・メソッド・リクエストボディ
 * - getChartUrl / openChartImage / SOURCE_LABELS
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import * as api from "./api";
import { setAccessToken, setApiKey } from "./auth";
import { jsonResponse, mockFetch, stubLocation } from "@/test/utils";

/** 直近の fetch 呼び出しの URL を取り出す */
function calledUrl(fetchMock: ReturnType<typeof mockFetch>, index = 0): string {
  return String(fetchMock.mock.calls[index][0]);
}

/** 直近の fetch 呼び出しの RequestInit を取り出す */
function calledInit(fetchMock: ReturnType<typeof mockFetch>, index = 0): RequestInit {
  return (fetchMock.mock.calls[index][1] ?? {}) as RequestInit;
}

describe("api — fetchAPI の共通挙動", () => {
  it("レスポンス JSON をそのまま返す", async () => {
    mockFetch(() => jsonResponse({ symbols: ["USDJPY", "EURUSD"] }));
    await expect(api.getSymbols()).resolves.toEqual({ symbols: ["USDJPY", "EURUSD"] });
  });

  it("常に cache: no-store を指定して古いデータを返さない", async () => {
    const f = mockFetch();
    await api.getSymbols();
    expect(calledInit(f).cache).toBe("no-store");
  });

  it("JWT がある場合は Authorization ヘッダーを自動付与する", async () => {
    setAccessToken("jwt-abc");
    const f = mockFetch();
    await api.getSymbols();
    expect(calledInit(f).headers).toMatchObject({ Authorization: "Bearer jwt-abc" });
  });

  it("API キーのみの場合は X-API-Key ヘッダーを自動付与する", async () => {
    setApiKey("fx_live_1");
    const f = mockFetch();
    await api.getSymbols();
    expect(calledInit(f).headers).toMatchObject({ "X-API-Key": "fx_live_1" });
  });

  it("呼び出し側のヘッダーが認証ヘッダーを上書きできる", async () => {
    setAccessToken("jwt-abc");
    const f = mockFetch();
    await api.authLogin("a@example.com", "password1");
    expect(calledInit(f).headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("NEXT_PUBLIC_API_URL 未設定時は相対パスでリクエストする", async () => {
    const f = mockFetch();
    await api.getSymbols();
    expect(calledUrl(f)).toBe("/api/symbols");
  });
});

describe("api — HTTP エラーのメッセージ変換", () => {
  it("レスポンスボディの detail をエラーメッセージに使う", async () => {
    mockFetch(() => jsonResponse({ detail: "シンボルが見つかりません" }, { status: 404 }));
    await expect(api.getSymbols()).rejects.toThrow("シンボルが見つかりません");
  });

  it("detail がオブジェクトの場合は JSON 文字列化する", async () => {
    mockFetch(() => jsonResponse({ detail: { loc: ["body"], msg: "invalid" } }, { status: 422 }));
    await expect(api.getSymbols()).rejects.toThrow(JSON.stringify({ loc: ["body"], msg: "invalid" }));
  });

  it("JSON でないエラー応答は『ステータス statusText』を使う", async () => {
    mockFetch(() => jsonResponse(undefined, { status: 500, statusText: "Internal Server Error" }));
    await expect(api.getSymbols()).rejects.toThrow("500 Internal Server Error");
  });

  it("403 はプラン確認の案内を付け足す", async () => {
    mockFetch(() => jsonResponse({ detail: "この機能は Pro プラン以上です" }, { status: 403 }));
    await expect(api.getSymbols()).rejects.toThrow(
      "この機能は Pro プラン以上です — /pricing でプランを確認してください。",
    );
  });

  it("429 は API 上限の案内を付け足す", async () => {
    mockFetch(() => jsonResponse({ detail: "rate limit" }, { status: 429 }));
    await expect(api.getSymbols()).rejects.toThrow(
      "rate limit — 本日の API 上限です。/settings からプランを確認してください。",
    );
  });

  it("502 かつ JSON ボディが無い場合は再試行を促すメッセージにする", async () => {
    mockFetch(() => jsonResponse(undefined, { status: 502, statusText: "Bad Gateway" }));
    await expect(api.getSymbols()).rejects.toThrow(/サーバーが応答しません（502）/);
  });

  it("502 でも detail がある場合はそれをそのまま使う", async () => {
    mockFetch(() => jsonResponse({ detail: "upstream closed" }, { status: 502 }));
    await expect(api.getSymbols()).rejects.toThrow("upstream closed");
  });

  it("504 で detail が短い場合はタイムアウトの定型文にする", async () => {
    mockFetch(() => jsonResponse({ detail: "timeout" }, { status: 504 }));
    await expect(api.getSymbols()).rejects.toThrow(
      "AI分析がタイムアウトしました。しばらく待って再実行してください。",
    );
  });

  it("504 で detail が十分に長い場合はそのまま返す", async () => {
    const detail = "AI 分析が 120 秒を超過したため中断されました";
    mockFetch(() => jsonResponse({ detail }, { status: 504 }));
    await expect(api.getSymbols()).rejects.toThrow(detail);
  });
});

describe("api — 401 時の自動ログアウト", () => {
  beforeEach(() => {
    stubLocation();
  });

  it("認証情報をクリアしてログイン画面へリダイレクトする", async () => {
    setAccessToken("jwt-expired");
    mockFetch(() => jsonResponse({ detail: "Not authenticated" }, { status: 401 }));

    await expect(api.getSymbols()).rejects.toThrow(
      "セッションの有効期限が切れました。再ログインしてください。",
    );

    expect(localStorage.getItem("fx_access_token")).toBeNull();
    expect(window.location.href).toBe("/login");
  });
});

describe("api — エンドポイントのパス構築", () => {
  it.each([
    ["getSymbols", () => api.getSymbols(), "/api/symbols"],
    ["getTechnicalAnalysis (既定 200 日)", () => api.getTechnicalAnalysis("USDJPY"), "/api/technical/USDJPY?days=200"],
    ["getTechnicalAnalysis (日数指定)", () => api.getTechnicalAnalysis("EURUSD", 90), "/api/technical/EURUSD?days=90"],
    ["getTradingSignals", () => api.getTradingSignals("USDJPY", 90), "/api/technical/USDJPY/signals?days=90"],
    ["getFundamentalData (フィルタなし)", () => api.getFundamentalData(), "/api/fundamental"],
    ["getFundamentalData (フィルタあり)", () => api.getFundamentalData("cpi"), "/api/fundamental?event_type=cpi"],
    ["getCalendar", () => api.getCalendar(), "/api/fundamental/calendar"],
    ["getMLPrediction", () => api.getMLPrediction("USDJPY"), "/api/ml/predict/USDJPY?days=200"],
    ["getAIStatus", () => api.getAIStatus(), "/api/ai/status"],
    ["getAINews", () => api.getAINews("USDJPY"), "/api/ai/news/USDJPY"],
    ["getAIFundamentalAnalysis", () => api.getAIFundamentalAnalysis("USDJPY"), "/api/ai/fundamental-analysis/USDJPY"],
    ["getAITradingDecision", () => api.getAITradingDecision("USDJPY"), "/api/ai/trading-decision/USDJPY"],
    ["getAIRisk", () => api.getAIRisk("USDJPY", 50000), "/api/ai/risk/USDJPY?account_balance=50000"],
    ["getAIReport", () => api.getAIReport("USDJPY"), "/api/ai/report/USDJPY?account_balance=10000"],
    ["getMultiTimeframe", () => api.getMultiTimeframe("USDJPY"), "/api/technical/USDJPY/multi-timeframe"],
    ["getSignalBacktest", () => api.getSignalBacktest("USDJPY", 365), "/api/technical/USDJPY/backtest?days=365"],
    ["getEventAlerts", () => api.getEventAlerts(72), "/api/fundamental/alerts?hours=72"],
    ["getDashboard", () => api.getDashboard("USDJPY"), "/api/dashboard?symbol=USDJPY&days=200"],
    ["getNewsAnalysis", () => api.getNewsAnalysis("USDJPY", 5), "/api/news/analysis/USDJPY?limit=5"],
    ["getBacktraderBacktest", () => api.getBacktraderBacktest("USDJPY", 200, 20000), "/api/backtest/backtrader/USDJPY?days=200&cash=20000"],
    ["getOandaStatus", () => api.getOandaStatus(), "/api/oanda/status"],
    ["getOandaOrders", () => api.getOandaOrders(10), "/api/oanda/orders?limit=10"],
    ["getTrendPrediction", () => api.getTrendPrediction("USDJPY"), "/api/analysis/trend/USDJPY?days=200"],
    ["getAnalysisNews", () => api.getAnalysisNews("USDJPY", 10), "/api/analysis/news/USDJPY?limit=10"],
    ["getSNSAnalysis", () => api.getSNSAnalysis("USDJPY", 10), "/api/analysis/sns/USDJPY?limit=10"],
    ["getEconomicAnalysis", () => api.getEconomicAnalysis("USDJPY"), "/api/analysis/economic/USDJPY"],
    ["getVolatilityPrediction", () => api.getVolatilityPrediction("USDJPY"), "/api/analysis/volatility/USDJPY?days=200"],
    ["getIntelligenceReport", () => api.getIntelligenceReport("USDJPY"), "/api/analysis/intelligence/USDJPY?days=200"],
    ["getMarketAnalysis", () => api.getMarketAnalysis("USDJPY"), "/api/analysis/market/USDJPY?days=200"],
    ["getRiskReport", () => api.getRiskReport("USDJPY"), "/api/analysis/risk-report/USDJPY?account_balance=10000&risk_percent=1&days=200"],
    ["authMe", () => api.authMe(), "/api/auth/me"],
    ["getBillingPlans", () => api.getBillingPlans(), "/api/billing/plans"],
    ["getBillingStatus", () => api.getBillingStatus(), "/api/billing/status"],
    ["getOandaSettings", () => api.getOandaSettings(), "/api/broker/oanda/settings"],
    ["listApiKeys", () => api.listApiKeys(), "/api/auth/api-keys"],
    ["getProSignals", () => api.getProSignals("USDJPY"), "/api/pro/signals/USDJPY?days=200"],
    ["getProMarketBrief", () => api.getProMarketBrief("USDJPY"), "/api/pro/market-brief/USDJPY"],
    ["getProCoaching", () => api.getProCoaching("USDJPY"), "/api/pro/coaching/USDJPY"],
    ["getProBacktest", () => api.getProBacktest("USDJPY"), "/api/pro/backtest/USDJPY?days=200"],
    ["getProRisk", () => api.getProRisk("USDJPY", 20000, 2), "/api/pro/risk/USDJPY?account_balance=20000&risk_percent=2"],
    ["getProPortfolio", () => api.getProPortfolio(), "/api/pro/portfolio"],
    ["getAutoTradeConfig", () => api.getAutoTradeConfig(), "/api/autotrade/config"],
    ["getAutoTradeStatus", () => api.getAutoTradeStatus(), "/api/autotrade/status"],
    ["getAutoTradePresets", () => api.getAutoTradePresets(), "/api/autotrade/presets"],
  ])("%s は %s を呼ぶ", async (_name, call, expected) => {
    const f = mockFetch();
    await call();
    expect(calledUrl(f)).toBe(expected);
  });

  it("getPositionSize は指定されたオプションのみをクエリに含める", async () => {
    const f = mockFetch();
    await api.getPositionSize("USDJPY", { accountBalance: 20000, stopPips: 30 });
    expect(calledUrl(f)).toBe("/api/position-size/USDJPY?account_balance=20000&stop_pips=30");
  });

  it("getPositionSize はオプション未指定ならクエリなしで呼ぶ", async () => {
    const f = mockFetch();
    await api.getPositionSize("USDJPY");
    expect(calledUrl(f)).toBe("/api/position-size/USDJPY");
  });

  it("getTradingViewSignals は symbol 省略時に limit のみ送る", async () => {
    const f = mockFetch();
    await api.getTradingViewSignals(undefined, 5);
    expect(calledUrl(f)).toBe("/api/tradingview/signals?limit=5");
  });

  it("getTradingViewSignals は symbol 指定時にフィルタを追加する", async () => {
    const f = mockFetch();
    await api.getTradingViewSignals("USDJPY");
    expect(calledUrl(f)).toBe("/api/tradingview/signals?limit=20&symbol=USDJPY");
  });

  it("getAutoTradeRuns は symbol 指定時にフィルタを追加する", async () => {
    const f = mockFetch();
    await api.getAutoTradeRuns("USDJPY", 10);
    expect(calledUrl(f)).toBe("/api/autotrade/runs?limit=10&symbol=USDJPY");
  });

  it("simulateAutoTrade は指定されたオプションのみをクエリに含める", async () => {
    const f = mockFetch();
    await api.simulateAutoTrade("USDJPY", { days: 365, presetId: "aggressive" });
    expect(calledUrl(f)).toBe("/api/autotrade/simulate/USDJPY?days=365&preset_id=aggressive");
  });
});

describe("api — 書き込み系エンドポイント", () => {
  it("syncMarketData は POST で呼ぶ", async () => {
    const f = mockFetch();
    await api.syncMarketData("USDJPY", 90);
    expect(calledUrl(f)).toBe("/api/data/sync/USDJPY?days=90");
    expect(calledInit(f).method).toBe("POST");
  });

  it("placeOandaOrder は注文内容をクエリに載せて POST する", async () => {
    const f = mockFetch();
    await api.placeOandaOrder("USDJPY", "sell", 2000);
    expect(calledUrl(f)).toBe("/api/oanda/orders?symbol=USDJPY&side=sell&units=2000");
    expect(calledInit(f).method).toBe("POST");
  });

  it("authRegister は org_name を含むボディを送る", async () => {
    const f = mockFetch();
    await api.authRegister("a@example.com", "password1", "Example 社");
    expect(calledUrl(f)).toBe("/api/auth/register");
    expect(calledInit(f).method).toBe("POST");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({
      email: "a@example.com",
      password: "password1",
      org_name: "Example 社",
    });
  });

  it("authLogin はメールとパスワードのみを送る", async () => {
    const f = mockFetch();
    await api.authLogin("a@example.com", "password1");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({
      email: "a@example.com",
      password: "password1",
    });
  });

  it("createBillingCheckout はプランを POST する", async () => {
    const f = mockFetch();
    await api.createBillingCheckout("pro");
    expect(calledUrl(f)).toBe("/api/billing/checkout");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({ plan: "pro" });
  });

  it("createBillingPortal はボディなしで POST する", async () => {
    const f = mockFetch();
    await api.createBillingPortal();
    expect(calledUrl(f)).toBe("/api/billing/portal");
    expect(calledInit(f).method).toBe("POST");
  });

  it("upgradePlan はプランを POST する", async () => {
    const f = mockFetch();
    await api.upgradePlan("enterprise");
    expect(calledUrl(f)).toBe("/api/billing/upgrade");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({ plan: "enterprise" });
  });

  it("updateOandaSettings は PUT で設定を送る", async () => {
    const f = mockFetch();
    await api.updateOandaSettings({ account_id: "101-001", environment: "live" });
    expect(calledUrl(f)).toBe("/api/broker/oanda/settings");
    expect(calledInit(f).method).toBe("PUT");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({
      account_id: "101-001",
      environment: "live",
    });
  });

  it("createApiKey はキー名を POST する", async () => {
    const f = mockFetch();
    await api.createApiKey("TradingView Webhook");
    expect(calledUrl(f)).toBe("/api/auth/api-keys");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({ name: "TradingView Webhook" });
  });

  it("sendProChat は session_id 未指定時に null を送る", async () => {
    const f = mockFetch();
    await api.sendProChat("今週の戦略は？", "USDJPY");
    expect(calledUrl(f)).toBe("/api/pro/chat");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({
      message: "今週の戦略は？",
      symbol: "USDJPY",
      session_id: null,
    });
  });

  it("sendProChat は session_id 指定時に会話を継続する", async () => {
    const f = mockFetch();
    await api.sendProChat("続きを教えて", "USDJPY", 42);
    expect(JSON.parse(String(calledInit(f).body)).session_id).toBe(42);
  });

  it("updateAutoTradeConfig は PUT で差分を送る", async () => {
    const f = mockFetch();
    await api.updateAutoTradeConfig({ enabled: true, min_confidence: 70 });
    expect(calledUrl(f)).toBe("/api/autotrade/config");
    expect(calledInit(f).method).toBe("PUT");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({ enabled: true, min_confidence: 70 });
  });

  it("evaluateAutoTrade / runAutoTradeSymbol / runAutoTradeAll は POST する", async () => {
    const f = mockFetch();
    await api.evaluateAutoTrade("USDJPY");
    await api.runAutoTradeSymbol("USDJPY");
    await api.runAutoTradeAll();

    expect(calledUrl(f, 0)).toBe("/api/autotrade/evaluate/USDJPY");
    expect(calledUrl(f, 1)).toBe("/api/autotrade/run/USDJPY");
    expect(calledUrl(f, 2)).toBe("/api/autotrade/run");
    expect([0, 1, 2].map((i) => calledInit(f, i).method)).toEqual(["POST", "POST", "POST"]);
  });

  it("applyAutoTradePreset は preset_id を POST する", async () => {
    const f = mockFetch();
    await api.applyAutoTradePreset("aggressive");
    expect(calledUrl(f)).toBe("/api/autotrade/presets/apply");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({ preset_id: "aggressive" });
  });

  it("autoSelectAutoTrade は preferred_symbols: null を必ず付与する", async () => {
    const f = mockFetch();
    await api.autoSelectAutoTrade({ capital: "small", horizon: "short", apply: true });
    expect(calledUrl(f)).toBe("/api/autotrade/autoselect");
    expect(JSON.parse(String(calledInit(f).body))).toEqual({
      capital: "small",
      horizon: "short",
      apply: true,
      preferred_symbols: null,
    });
  });
});

describe("api — getChartUrl", () => {
  it("シンボルと日数から PNG の URL を組み立てる", () => {
    expect(api.getChartUrl("USDJPY")).toBe("/api/chart/USDJPY?days=200");
    expect(api.getChartUrl("EURUSD", 90)).toBe("/api/chart/EURUSD?days=90");
  });
});

describe("api — openChartImage", () => {
  beforeEach(() => {
    stubLocation();
  });

  it("認証ヘッダー付きで取得し Blob URL を新規タブで開く", async () => {
    setAccessToken("jwt-abc");
    const f = mockFetch(() => jsonResponse(null, { status: 200, blob: new Blob(["png"]) }));
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:chart");
    const open = vi.spyOn(window, "open").mockReturnValue({} as Window);

    await api.openChartImage("USDJPY", 90);

    expect(calledUrl(f)).toBe("/api/chart/USDJPY?days=90");
    expect(calledInit(f).headers).toMatchObject({ Authorization: "Bearer jwt-abc" });
    expect(createObjectURL).toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith("blob:chart", "_blank", "noopener,noreferrer");
  });

  it("60 秒後に Blob URL を解放する", async () => {
    vi.useFakeTimers();
    try {
      mockFetch(() => jsonResponse(null, { status: 200, blob: new Blob(["png"]) }));
      vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:chart");
      const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
      vi.spyOn(window, "open").mockReturnValue({} as Window);

      await api.openChartImage("USDJPY");
      expect(revoke).not.toHaveBeenCalled();

      vi.advanceTimersByTime(60_000);
      expect(revoke).toHaveBeenCalledWith("blob:chart");
    } finally {
      vi.useRealTimers();
    }
  });

  it("ポップアップがブロックされた場合は Blob URL を解放して例外を投げる", async () => {
    mockFetch(() => jsonResponse(null, { status: 200, blob: new Blob(["png"]) }));
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:chart");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(window, "open").mockReturnValue(null);

    await expect(api.openChartImage("USDJPY")).rejects.toThrow(
      "ポップアップがブロックされました。ブラウザの設定を確認してください。",
    );
    expect(revoke).toHaveBeenCalledWith("blob:chart");
  });

  it("HTTP エラー時は detail を持つ例外を投げる", async () => {
    mockFetch(() => jsonResponse({ detail: "チャート生成に失敗" }, { status: 500 }));
    await expect(api.openChartImage("USDJPY")).rejects.toThrow("チャート生成に失敗");
  });

  it("401 の場合は認証情報をクリアしてログインへ遷移する", async () => {
    setAccessToken("jwt-expired");
    mockFetch(() => jsonResponse({ detail: "Not authenticated" }, { status: 401 }));

    await expect(api.openChartImage("USDJPY")).rejects.toThrow(
      "セッションの有効期限が切れました。再ログインしてください。",
    );
    expect(localStorage.getItem("fx_access_token")).toBeNull();
    expect(window.location.href).toBe("/login");
  });
});

describe("api — SOURCE_LABELS", () => {
  it("データソース識別子を表示名に変換する", () => {
    expect(api.SOURCE_LABELS.database).toBe("PostgreSQL");
    expect(api.SOURCE_LABELS.yahoo_finance).toBe("Yahoo Finance");
    expect(api.SOURCE_LABELS.sample).toBe("サンプルデータ");
  });

  it("未知の識別子は未定義（呼び出し側で元の値にフォールバックする）", () => {
    expect(api.SOURCE_LABELS.unknown_source).toBeUndefined();
  });
});
