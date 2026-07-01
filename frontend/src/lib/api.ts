/**
 * @file api.ts
 * @description フロントエンド共通 API クライアントモジュール。
 *
 * バックエンド FastAPI サーバーへのすべての HTTP リクエストをここで一元管理する。
 * - `fetchAPI` が基底となる汎用ラッパーで、認証ヘッダーの付与・エラーハンドリング・
 *   401/403/429/502/504 ごとのユーザーフレンドリーなメッセージ変換を担う。
 * - 各エクスポート関数は特定のエンドポイントに対応した薄いラッパーであり、
 *   型安全なレスポンスを返す。
 * - SaaS モード（NEXT_PUBLIC_SAAS_ENABLED=true）では 401 エラー時に自動でログアウト
 *   してログイン画面へリダイレクトする。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { authHeaders, clearAuth, SAAS_ENABLED } from "./auth";
import type { SignalBacktest, BacktraderResult, WalkForwardResult } from "@/types";

/** バックエンド API のベース URL。環境変数 NEXT_PUBLIC_API_URL から取得する。未設定の場合は同一オリジン相対パスを使用。 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

/**
 * バックエンド API への汎用フェッチラッパー。
 *
 * - `authHeaders()` で JWT Bearer トークンまたは X-API-Key ヘッダーを自動付与する。
 * - レスポンスが ok でない場合、ステータスコードに応じた日本語エラーメッセージを生成する。
 * - SaaS モードで 401 が返った場合は認証情報をクリアしてログインページへリダイレクトする。
 * - キャッシュは常に `no-store` に設定し、古いデータを返さないようにする。
 *
 * @template T - 期待するレスポンスボディの型
 * @param path - API パス（例: `/api/symbols`）。`API_BASE` に結合される。
 * @param options - `fetch` に渡す追加オプション（メソッド・ボディ・ヘッダーなど）
 * @returns パースされた JSON レスポンスを型 T として返す Promise
 * @throws {Error} HTTP エラー時にユーザー向けメッセージを持つ Error をスロー
 */
async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...options,
    headers: {
      // 認証ヘッダー（JWT Bearer または X-API-Key）を先に展開し、
      // 呼び出し元の追加ヘッダーで上書きできるようにする
      ...authHeaders(),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    // エラー詳細をレスポンスボディから取り出す（取り出せない場合はステータス文字列をそのまま使用）
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // レスポンスが JSON でない場合（502 など）は既定値を使用
      if (res.status === 502) {
        detail = "502 Bad Gateway";
      }
    }
    // 401: 未認証 — SaaS モードでは自動ログアウト＆リダイレクト
    if (SAAS_ENABLED && res.status === 401 && typeof window !== "undefined") {
      clearAuth();
      window.location.href = "/login";
      throw new Error("セッションの有効期限が切れました。再ログインしてください。");
    }
    // 403: 権限不足（プランによるアクセス制限など）
    if (res.status === 403) {
      throw new Error(`${detail} — /pricing でプランを確認してください。`);
    }
    // 429: レートリミット超過（1日の API 上限に達した場合）
    if (res.status === 429) {
      throw new Error(`${detail} — 本日の API 上限です。/settings からプランを確認してください。`);
    }
    // 502: バックエンドが応答しない（AI 分析の場合はタイムアウトが多い）
    if (res.status === 502) {
      throw new Error(
        detail === "502 Bad Gateway" || detail === "502"
          ? "サーバーが応答しません（502）。AI分析は時間がかかることがあります。再試行するか、総合レポートタブをお試しください。"
          : detail,
      );
    }
    // 504: ゲートウェイタイムアウト（AI 分析などの長時間処理で発生）
    if (res.status === 504) {
      throw new Error(
        typeof detail === "string" && detail.length > 10
          ? detail
          : "AI分析がタイムアウトしました。しばらく待って再実行してください。",
      );
    }
    throw new Error(detail);
  }
  return res.json();
}

/**
 * 利用可能な通貨ペアシンボル一覧を取得する。
 *
 * エンドポイント: GET /api/symbols
 * 認証: authHeaders() により JWT または API キーを自動付与
 *
 * @returns `{ symbols: string[] }` — 利用可能なシンボルの配列
 */
export async function getSymbols(): Promise<{ symbols: string[] }> {
  return fetchAPI("/api/symbols");
}

/**
 * 指定シンボルのテクニカル分析データを取得する。
 *
 * エンドポイント: GET /api/technical/{symbol}?days={days}
 * 返却データには OHLCV・移動平均・ボリンジャーバンド・MACD・RSI・一目均衡表などが含まれる。
 *
 * @param symbol - 通貨ペアシンボル（例: `"USDJPY"`）
 * @param days - 取得する過去データの日数（デフォルト 200 日）
 * @returns {@link TechnicalAnalysis} オブジェクト
 */
export async function getTechnicalAnalysis(
  symbol: string,
  days = 200
): Promise<import("@/types").TechnicalAnalysis> {
  return fetchAPI(`/api/technical/${symbol}?days=${days}`);
}

/**
 * 指定シンボルのトレードシグナル一覧を取得する。
 *
 * エンドポイント: GET /api/technical/{symbol}/signals?days={days}
 * RSI・MACD・ボリンジャーバンドなどの指標から生成された売買シグナルが含まれる。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - 取得する過去データの日数（デフォルト 200 日）
 * @returns シンボル・シグナル配列・現在価格・データソースを含むオブジェクト
 */
export async function getTradingSignals(
  symbol: string,
  days = 200
): Promise<{ symbol: string; signals: import("@/types").TradingSignal[]; price: number; source?: string }> {
  return fetchAPI(`/api/technical/${symbol}/signals?days=${days}`);
}

/**
 * ファンダメンタルズデータ（経済指標）を取得する。
 *
 * エンドポイント: GET /api/fundamental[?event_type={eventType}]
 * GDP・CPI・雇用統計などの経済イベントデータが含まれる。
 *
 * @param eventType - フィルタするイベント種別（省略時は全種別）
 * @returns {@link FundamentalData} オブジェクト
 */
export async function getFundamentalData(
  eventType?: string
): Promise<import("@/types").FundamentalData> {
  const query = eventType ? `?event_type=${eventType}` : "";
  return fetchAPI(`/api/fundamental${query}`);
}

/**
 * 経済カレンダーイベント一覧を取得する。
 *
 * エンドポイント: GET /api/fundamental/calendar
 *
 * @returns 経済イベントの配列を含むオブジェクト
 */
export async function getCalendar(): Promise<{ events: import("@/types").CalendarEvent[] }> {
  return fetchAPI("/api/fundamental/calendar");
}

/**
 * 機械学習モデルによる価格予測を取得する。
 *
 * エンドポイント: GET /api/ml/predict/{symbol}?days={days}
 * バックエンドでランダムフォレスト等のモデルによる翌日終値予測が行われる。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - 学習に使用する過去データの日数（デフォルト 200 日）
 * @returns {@link MLPrediction} オブジェクト
 */
export async function getMLPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").MLPrediction> {
  return fetchAPI(`/api/ml/predict/${symbol}?days=${days}`);
}

/**
 * 市場データをデータベースに同期する。
 *
 * エンドポイント: POST /api/data/sync/{symbol}?days={days}
 * Yahoo Finance などのデータソースから最新の OHLCV データを取得して保存する。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - 同期する日数（デフォルト 200 日）
 * @returns 同期結果（シンボル・同期行数・最新終値・最新日付）
 */
export async function syncMarketData(
  symbol: string,
  days = 200
): Promise<{ symbol: string; rows_synced: number; latest_close: number; latest_date: string }> {
  return fetchAPI(`/api/data/sync/${symbol}?days=${days}`, { method: "POST" });
}

/**
 * チャート画像の URL を生成する（認証なし）。
 *
 * 主にブラウザ上で直接 `<img>` タグに使用するための URL を返す。
 * 認証が必要な場合は代わりに {@link openChartImage} を使用すること。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - 表示する日数（デフォルト 200 日）
 * @returns チャート PNG の URL 文字列
 */
export function getChartUrl(symbol: string, days = 200): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  return `${base}/api/chart/${symbol}?days=${days}`;
}

/**
 * 認証ヘッダー付きでチャート PNG を取得し、新しいタブで表示する。
 *
 * エンドポイント: GET /api/chart/{symbol}?days={days}
 * 認証: authHeaders() により JWT または API キーを自動付与
 *
 * Blob URL を生成して新規タブで開き、60 秒後に自動解放する。
 * ポップアップがブロックされた場合はエラーをスローする。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - 表示する日数（デフォルト 200 日）
 * @throws {Error} HTTP エラー・ポップアップブロック時
 */
export async function openChartImage(symbol: string, days = 200): Promise<void> {
  const res = await fetch(getChartUrl(symbol, days), {
    cache: "no-store",
    headers: authHeaders(),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* PNG 以外のエラー応答 */
    }
    if (SAAS_ENABLED && res.status === 401 && typeof window !== "undefined") {
      clearAuth();
      window.location.href = "/login";
      throw new Error("セッションの有効期限が切れました。再ログインしてください。");
    }
    throw new Error(detail);
  }
  // レスポンスを Blob に変換してオブジェクト URL を生成
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  // 新しいタブで画像を開く（noopener で親ページへのアクセスを防止）
  const tab = window.open(objectUrl, "_blank", "noopener,noreferrer");
  if (!tab) {
    URL.revokeObjectURL(objectUrl);
    throw new Error("ポップアップがブロックされました。ブラウザの設定を確認してください。");
  }
  // 60 秒後にオブジェクト URL を解放してメモリリークを防止
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

/** データソース識別子をユーザー向け表示名に変換するマッピング */
export const SOURCE_LABELS: Record<string, string> = {
  database: "PostgreSQL",
  yahoo_finance: "Yahoo Finance",
  sample: "サンプルデータ",
};

/**
 * AI（OpenAI）の設定状態を取得する。
 *
 * エンドポイント: GET /api/ai/status
 * API キーが設定済みかどうかと、使用中のモデル名を返す。
 *
 * @returns 設定済みフラグ・モデル名・キープレビューを含むオブジェクト
 */
export async function getAIStatus(): Promise<{
  configured: boolean;
  model?: string;
  key_preview?: string | null;
}> {
  return fetchAPI("/api/ai/status");
}

/**
 * AI によるニュース分析を取得する。
 *
 * エンドポイント: GET /api/ai/news/{symbol}
 * OpenAI GPT によって収集ニュースのセンチメント分析・市場への影響評価が行われる。
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link AINewsAnalysis} オブジェクト
 */
export async function getAINews(symbol: string): Promise<import("@/types").AINewsAnalysis> {
  return fetchAPI(`/api/ai/news/${symbol}`);
}

/**
 * AI によるファンダメンタルズ分析を取得する。
 *
 * エンドポイント: GET /api/ai/fundamental-analysis/{symbol}
 * 基軸通貨・決済通貨の分析と将来のリスクシナリオが含まれる。
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link AIFundamentalAnalysis} オブジェクト
 */
export async function getAIFundamentalAnalysis(
  symbol: string
): Promise<import("@/types").AIFundamentalAnalysis> {
  return fetchAPI(`/api/ai/fundamental-analysis/${symbol}`);
}

/**
 * AI によるトレード判断（エントリー・利確・損切り価格含む）を取得する。
 *
 * エンドポイント: GET /api/ai/trading-decision/{symbol}
 * テクニカル・ファンダメンタルズ・ニュースを総合した最終的なトレード推奨が得られる。
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link AITradingDecision} オブジェクト
 */
export async function getAITradingDecision(
  symbol: string
): Promise<import("@/types").AITradingDecision> {
  return fetchAPI(`/api/ai/trading-decision/${symbol}`);
}

/**
 * AI によるリスク評価を取得する。
 *
 * エンドポイント: GET /api/ai/risk/{symbol}?account_balance={accountBalance}
 * 推奨ポジションサイズ・最大損失額・レバレッジ推奨値などが含まれる。
 *
 * @param symbol - 通貨ペアシンボル
 * @param accountBalance - 口座残高（USD）（デフォルト 10,000 USD）
 * @returns {@link AIRiskAssessment} オブジェクト
 */
export async function getAIRisk(
  symbol: string,
  accountBalance = 10000
): Promise<import("@/types").AIRiskAssessment> {
  return fetchAPI(`/api/ai/risk/${symbol}?account_balance=${accountBalance}`);
}

/**
 * AI による総合レポート（ニュース・ファンダメンタルズ・トレード判断・リスク管理をまとめたもの）を取得する。
 *
 * エンドポイント: GET /api/ai/report/{symbol}?account_balance={accountBalance}
 * 1 回のリクエストで {@link AIFullReport} の全フィールドが返される。
 * AI 処理が重いため 504 タイムアウトが発生しやすい。
 *
 * @param symbol - 通貨ペアシンボル
 * @param accountBalance - 口座残高（USD）（デフォルト 10,000 USD）
 * @returns {@link AIFullReport} オブジェクト
 */
export async function getAIReport(
  symbol: string,
  accountBalance = 10000
): Promise<import("@/types").AIFullReport> {
  return fetchAPI(`/api/ai/report/${symbol}?account_balance=${accountBalance}`);
}

/**
 * マルチタイムフレーム分析データを取得する。
 *
 * エンドポイント: GET /api/technical/{symbol}/multi-timeframe
 * 1H・4H・1D など複数時間軸のトレンド整合性が確認できる。
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link MultiTimeframeAnalysis} オブジェクト
 */
export async function getMultiTimeframe(
  symbol: string
): Promise<import("@/types").MultiTimeframeAnalysis> {
  return fetchAPI(`/api/technical/${symbol}/multi-timeframe`);
}

/**
 * シグナルバックテスト結果を取得する。
 *
 * エンドポイント: GET /api/technical/{symbol}/backtest?days={days}
 * 過去シグナルに基づく勝率・平均リターン等が含まれる。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - バックテスト期間（日数）（デフォルト 200 日）
 * @returns {@link SignalBacktest} オブジェクト
 */
export async function getSignalBacktest(
  symbol: string,
  days = 200
): Promise<import("@/types").SignalBacktest> {
  return fetchAPI(`/api/technical/${symbol}/backtest?days=${days}`);
}

/**
 * 推奨ポジションサイズを計算して取得する。
 *
 * エンドポイント: GET /api/position-size/{symbol}[?account_balance=...&risk_percent=...&stop_pips=...&days=...]
 * リスク許容度・ATR ベースのストップロスに基づいた最適ロット数が計算される。
 *
 * @param symbol - 通貨ペアシンボル
 * @param opts - オプション（口座残高・リスク率・ストップ幅・データ日数）
 * @returns {@link PositionSizeResult} オブジェクト
 */
export async function getPositionSize(
  symbol: string,
  opts: { accountBalance?: number; riskPercent?: number; stopPips?: number; days?: number } = {}
): Promise<import("@/types").PositionSizeResult> {
  const params = new URLSearchParams();
  if (opts.accountBalance) params.set("account_balance", String(opts.accountBalance));
  if (opts.riskPercent) params.set("risk_percent", String(opts.riskPercent));
  if (opts.stopPips) params.set("stop_pips", String(opts.stopPips));
  if (opts.days) params.set("days", String(opts.days));
  const q = params.toString();
  return fetchAPI(`/api/position-size/${symbol}${q ? `?${q}` : ""}`);
}

/**
 * 直近の高インパクト経済イベントアラートを取得する。
 *
 * エンドポイント: GET /api/fundamental/alerts?hours={hours}
 *
 * @param hours - 何時間以内のイベントを対象にするか（デフォルト 48 時間）
 * @returns アラート配列と対象時間数を含むオブジェクト
 */
export async function getEventAlerts(
  hours = 48
): Promise<{ alerts: import("@/types").EventAlert[]; within_hours: number }> {
  return fetchAPI(`/api/fundamental/alerts?hours=${hours}`);
}

/**
 * ダッシュボード用の統合データを一括取得する。
 *
 * エンドポイント: GET /api/dashboard?symbol={symbol}&days={days}
 * 価格・シグナル・マルチタイムフレーム・ニュース・バックテスト等がまとめて返される。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link DashboardData} オブジェクト
 */
export async function getDashboard(
  symbol: string,
  days = 200
): Promise<import("@/types").DashboardData> {
  return fetchAPI(`/api/dashboard?symbol=${symbol}&days=${days}`);
}

/**
 * TradingView Webhook 経由で受信したシグナル一覧を取得する。
 *
 * エンドポイント: GET /api/tradingview/signals?limit={limit}[&symbol={symbol}]
 *
 * @param symbol - フィルタするシンボル（省略時は全シンボル）
 * @param limit - 取得件数上限（デフォルト 20 件）
 * @returns TradingView シグナルの配列を含むオブジェクト
 */
export async function getTradingViewSignals(
  symbol?: string,
  limit = 20
): Promise<{ signals: import("@/types").TradingViewSignal[] }> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  return fetchAPI(`/api/tradingview/signals?${q}`);
}

/**
 * ニュース収集＋ML センチメント分析の結果を取得する。
 *
 * エンドポイント: GET /api/news/analysis/{symbol}?limit={limit}
 *
 * @param symbol - 通貨ペアシンボル
 * @param limit - 取得記事数（デフォルト 8 件）
 * @returns {@link NewsAnalysisResult} オブジェクト（ML と OpenAI 両方の結果を含む）
 */
export async function getNewsAnalysis(
  symbol: string,
  limit = 8
): Promise<import("@/types").NewsAnalysisResult> {
  return fetchAPI(`/api/news/analysis/${symbol}?limit=${limit}`);
}

/**
 * Backtrader エンジンによるバックテスト結果を取得する。
 *
 * エンドポイント: GET /api/backtest/backtrader/{symbol}?days={days}&cash={cash}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - バックテスト期間（日数）（デフォルト 200 日）
 * @param cash - 初期資金（USD）（デフォルト 10,000 USD）
 * @returns {@link BacktraderResult} オブジェクト
 */
export async function getBacktraderBacktest(
  symbol: string,
  days = 200,
  cash = 10000
): Promise<import("@/types").BacktraderResult> {
  return fetchAPI(`/api/backtest/backtrader/${symbol}?days=${days}&cash=${cash}`);
}

/**
 * OANDA ブローカーの接続状態・口座サマリーを取得する。
 *
 * エンドポイント: GET /api/oanda/status
 *
 * @returns {@link OandaStatus} オブジェクト（残高・モード・未実現損益など）
 */
export async function getOandaStatus(): Promise<import("@/types").OandaStatus> {
  return fetchAPI("/api/oanda/status");
}

/**
 * OANDA の注文一覧を取得する。
 *
 * エンドポイント: GET /api/oanda/orders?limit={limit}
 *
 * @param limit - 取得件数上限（デフォルト 20 件）
 * @returns 注文オブジェクトの配列を含むオブジェクト
 */
export async function getOandaOrders(
  limit = 20
): Promise<{ orders: import("@/types").BrokerOrder[] }> {
  return fetchAPI(`/api/oanda/orders?limit=${limit}`);
}

/**
 * OANDA に新規注文を発注する。
 *
 * エンドポイント: POST /api/oanda/orders?symbol={symbol}&side={side}&units={units}
 *
 * @param symbol - 通貨ペアシンボル
 * @param side - 売買方向（`"buy"` または `"sell"`）
 * @param units - 取引単位（OANDA の units 単位）
 * @returns 作成された {@link BrokerOrder} オブジェクト
 */
export async function placeOandaOrder(
  symbol: string,
  side: "buy" | "sell",
  units: number
): Promise<import("@/types").BrokerOrder> {
  const q = new URLSearchParams({ symbol, side, units: String(units) });
  return fetchAPI(`/api/oanda/orders?${q}`, { method: "POST" });
}

/**
 * ML・ルールベースを組み合わせたトレンド予測を取得する。
 *
 * エンドポイント: GET /api/analysis/trend/{symbol}?days={days}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link TrendPrediction} オブジェクト
 */
export async function getTrendPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").TrendPrediction> {
  return fetchAPI(`/api/analysis/trend/${symbol}?days=${days}`);
}

/**
 * 分析用ニュース分析（analysis エンドポイント）を取得する。
 *
 * エンドポイント: GET /api/analysis/news/{symbol}?limit={limit}
 *
 * @param symbol - 通貨ペアシンボル
 * @param limit - 取得記事数（デフォルト 8 件）
 * @returns {@link NewsAnalysisResult} オブジェクト
 */
export async function getAnalysisNews(
  symbol: string,
  limit = 8
): Promise<import("@/types").NewsAnalysisResult> {
  return fetchAPI(`/api/analysis/news/${symbol}?limit=${limit}`);
}

/**
 * SNS（Reddit 等）のセンチメント分析を取得する。
 *
 * エンドポイント: GET /api/analysis/sns/{symbol}?limit={limit}
 *
 * @param symbol - 通貨ペアシンボル
 * @param limit - 取得投稿数（デフォルト 10 件）
 * @returns {@link SNSAnalysis} オブジェクト
 */
export async function getSNSAnalysis(
  symbol: string,
  limit = 10
): Promise<import("@/types").SNSAnalysis> {
  return fetchAPI(`/api/analysis/sns/${symbol}?limit=${limit}`);
}

/**
 * 経済指標ベースの通貨ペア分析を取得する。
 *
 * エンドポイント: GET /api/analysis/economic/{symbol}
 * GDP・CPI・金利差などから通貨ペアのバイアスが算出される。
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link EconomicAnalysis} オブジェクト
 */
export async function getEconomicAnalysis(
  symbol: string
): Promise<import("@/types").EconomicAnalysis> {
  return fetchAPI(`/api/analysis/economic/${symbol}`);
}

/**
 * ボラティリティ予測を取得する。
 *
 * エンドポイント: GET /api/analysis/volatility/{symbol}?days={days}
 * ATR・GARCH モデルによる予測ボラティリティが含まれる。
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link VolatilityPrediction} オブジェクト
 */
export async function getVolatilityPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").VolatilityPrediction> {
  return fetchAPI(`/api/analysis/volatility/${symbol}?days=${days}`);
}

/**
 * インテリジェンスレポート（トレンド・ニュース・SNS・経済・ボラティリティを統合した総合分析）を取得する。
 *
 * エンドポイント: GET /api/analysis/intelligence/{symbol}?days={days}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link IntelligenceReport} オブジェクト
 */
export async function getIntelligenceReport(
  symbol: string,
  days = 200
): Promise<import("@/types").IntelligenceReport> {
  return fetchAPI(`/api/analysis/intelligence/${symbol}?days=${days}`);
}

/**
 * マーケット分析（レジーム・キーレベル・モメンタム・相関・セッション・イベントリスク）を取得する。
 *
 * エンドポイント: GET /api/analysis/market/{symbol}?days={days}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link MarketAnalysis} オブジェクト
 */
export async function getMarketAnalysis(
  symbol: string,
  days = 200
): Promise<import("@/types").MarketAnalysis> {
  return fetchAPI(`/api/analysis/market/${symbol}?days=${days}`);
}

/**
 * 総合リスクレポート（VaR・シナリオ分析・ストレステスト・チェックリスト含む）を取得する。
 *
 * エンドポイント: GET /api/analysis/risk-report/{symbol}?account_balance=...&risk_percent=...&days=...
 *
 * @param symbol - 通貨ペアシンボル
 * @param accountBalance - 口座残高（USD）（デフォルト 10,000 USD）
 * @param riskPercent - 1 トレードあたりのリスク率（%）（デフォルト 1%）
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link RiskReport} オブジェクト
 */
export async function getRiskReport(
  symbol: string,
  accountBalance = 10000,
  riskPercent = 1,
  days = 200
): Promise<import("@/types").RiskReport> {
  return fetchAPI(
    `/api/analysis/risk-report/${symbol}?account_balance=${accountBalance}&risk_percent=${riskPercent}&days=${days}`
  );
}

/**
 * 認証済みセッション情報（ユーザー・テナント・利用状況・機能フラグ）を表すインターフェース。
 *
 * `/api/auth/me` のレスポンス型であり、{@link AuthContext} でグローバルに保持される。
 */
export interface AuthSession {
  /** ログイン中のユーザー情報 */
  user: {
    /** ユーザー ID */
    id: number;
    /** メールアドレス */
    email: string;
    /** ロール（`"admin"` / `"user"` など） */
    role: string;
    /** 所属テナントの ID */
    tenant_id: number;
  };
  /** テナント（組織）情報 */
  tenant: {
    /** テナント ID */
    id: number;
    /** テナント名 */
    name: string;
    /** URL スラッグ */
    slug: string;
    /** 現在のプラン識別子（`"free"` / `"pro"` など） */
    plan: string;
    /** Stripe サブスクリプションの有無 */
    has_stripe_subscription?: boolean;
  };
  /** API 利用状況（1 日あたりの呼び出し数・上限・残数） */
  usage: {
    /** 本日の API 呼び出し回数 */
    daily_calls: number;
    /** 1 日あたりの上限 */
    daily_limit: number;
    /** 残り呼び出し可能回数 */
    remaining: number;
    /** 使用率（0〜100）*/
    usage_percent?: number;
    /** 利用状況レベル（`"ok"` / `"warning"` / `"critical"` / `"exhausted"`）*/
    usage_level?: "ok" | "warning" | "critical" | "exhausted";
  };
  /** プランごとに有効化されている機能フラグのマップ */
  features: Record<string, boolean | number>;
  /** Stripe 決済情報（SaaS モードのみ） */
  billing?: { stripe_customer: boolean; stripe_subscription: boolean };
}

/**
 * 課金プラン情報を表すインターフェース。
 *
 * `/api/billing/plans` のレスポンスに含まれる各プランの定義。
 */
export interface BillingPlan {
  /** プラン識別子（`"free"` / `"pro"` / `"enterprise"` など） */
  id: string;
  /** プランの表示名 */
  name: string;
  /** 月額料金（USD） */
  price_monthly_usd: number;
  /** 1 日あたりの API 呼び出し上限 */
  daily_api_limit: number;
  /** このプランで有効な機能フラグのマップ */
  features: Record<string, boolean | number>;
}

/**
 * 新規ユーザー登録 API を呼び出す。
 *
 * エンドポイント: POST /api/auth/register
 * リクエストボディ: `{ email, password, org_name }`
 *
 * @param email - 登録するメールアドレス
 * @param password - パスワード
 * @param orgName - 組織名（テナント名として使用される）
 * @returns アクセストークン・ユーザー情報・テナント情報
 */
export async function authRegister(
  email: string,
  password: string,
  orgName: string
): Promise<{ access_token: string; user: AuthSession["user"]; tenant: AuthSession["tenant"] }> {
  return fetchAPI("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, org_name: orgName }),
  });
}

/**
 * ログイン API を呼び出して JWT アクセストークンを取得する。
 *
 * エンドポイント: POST /api/auth/login
 * リクエストボディ: `{ email, password }`
 *
 * @param email - ログインするメールアドレス
 * @param password - パスワード
 * @returns アクセストークン・ユーザー情報・テナント情報
 */
export async function authLogin(
  email: string,
  password: string
): Promise<{ access_token: string; user: AuthSession["user"]; tenant: AuthSession["tenant"] }> {
  return fetchAPI("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

/**
 * 現在のログインユーザーのセッション情報を取得する。
 *
 * エンドポイント: GET /api/auth/me
 * 認証: JWT Bearer トークンが必須
 *
 * @returns {@link AuthSession} オブジェクト
 */
export async function authMe(): Promise<AuthSession> {
  return fetchAPI("/api/auth/me");
}

/**
 * 利用可能な課金プラン一覧と SaaS/Stripe の有効状態を取得する。
 *
 * エンドポイント: GET /api/billing/plans
 *
 * @returns プラン一覧・SaaS 有効フラグ・Stripe 有効フラグ
 */
export async function getBillingPlans(): Promise<{
  plans: BillingPlan[];
  saas_enabled: boolean;
  stripe_enabled?: boolean;
}> {
  return fetchAPI("/api/billing/plans");
}

/**
 * Stripe チェックアウトセッションを作成してチェックアウト URL を取得する。
 *
 * エンドポイント: POST /api/billing/checkout
 * リクエストボディ: `{ plan }`
 *
 * @param plan - 購入するプランの識別子
 * @returns Stripe チェックアウトページの URL
 */
export async function createBillingCheckout(plan: string): Promise<{ checkout_url: string }> {
  return fetchAPI("/api/billing/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
}

/**
 * Stripe カスタマーポータルセッションを作成してポータル URL を取得する。
 *
 * エンドポイント: POST /api/billing/portal
 * プランのアップグレード・ダウングレード・解約操作が行えるページへ誘導する。
 *
 * @returns Stripe カスタマーポータルの URL
 */
export async function createBillingPortal(): Promise<{ portal_url: string }> {
  return fetchAPI("/api/billing/portal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

/**
 * 現在のテナントの課金状況（プラン・API 利用状況・Stripe 情報）を取得する。
 *
 * エンドポイント: GET /api/billing/status
 *
 * @returns プラン名・月額・API 上限・Stripe 状態・利用状況を含むオブジェクト
 */
export async function getBillingStatus(): Promise<{
  plan: string;
  plan_name: string;
  price_monthly_usd: number;
  daily_api_limit: number;
  stripe_enabled: boolean;
  has_active_subscription: boolean;
  usage: { daily_calls: number; daily_limit: number; remaining: number; usage_percent: number };
}> {
  return fetchAPI("/api/billing/status");
}

/**
 * OANDA ブローカー設定（API トークン・口座 ID・環境）を取得する。
 *
 * エンドポイント: GET /api/broker/oanda/settings
 *
 * @returns 設定オブジェクトと口座サマリー
 */
export async function getOandaSettings(): Promise<{
  settings: {
    account_id?: string;
    environment?: string;
    api_token_set?: boolean;
    api_token_masked?: string;
  } | null;
  account_summary: {
    configured: boolean;
    mode: string;
    balance: number;
    source?: string;
    message?: string;
  };
}> {
  return fetchAPI("/api/broker/oanda/settings");
}

/**
 * OANDA ブローカー設定を更新する。
 *
 * エンドポイント: PUT /api/broker/oanda/settings
 * リクエストボディ: `{ api_token?, account_id?, environment?, clear_token? }`
 *
 * @param body - 更新する設定項目（`clear_token: true` でトークンを削除）
 * @returns 更新後の設定オブジェクト
 */
export async function updateOandaSettings(body: {
  api_token?: string;
  account_id?: string;
  environment?: "practice" | "live";
  clear_token?: boolean;
}): Promise<{ settings: Record<string, unknown> }> {
  return fetchAPI("/api/broker/oanda/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * テナントのプランをアップグレードする（Stripe を使用しない直接アップグレード）。
 *
 * エンドポイント: POST /api/billing/upgrade
 * リクエストボディ: `{ plan }`
 *
 * @param plan - アップグレード先プランの識別子
 * @returns 更新後のテナント情報
 */
export async function upgradePlan(plan: string): Promise<{ tenant: AuthSession["tenant"] }> {
  return fetchAPI("/api/billing/upgrade", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
}

/**
 * テナントの API キー一覧を取得する。
 *
 * エンドポイント: GET /api/auth/api-keys
 *
 * @returns API キーのメタデータ（ID・名前・プレフィックス・作成日時）の配列
 */
export async function listApiKeys(): Promise<{
  keys: { id: number; name: string; key_prefix: string; created_at: string | null }[];
}> {
  return fetchAPI("/api/auth/api-keys");
}

/**
 * 新しい API キーを発行する。
 *
 * エンドポイント: POST /api/auth/api-keys
 * リクエストボディ: `{ name }`
 * 発行された `api_key` は一度しか表示されないため、呼び出し元で安全に保存すること。
 *
 * @param name - キーの識別名
 * @returns 発行された API キー（平文）とメタデータ
 */
export async function createApiKey(name: string): Promise<{
  id: number;
  name: string;
  api_key: string;
  key_prefix: string;
}> {
  return fetchAPI("/api/auth/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

/**
 * Pro プラン向けの AI 統合シグナル（ルールベース + ML + AI 判断）を取得する。
 *
 * エンドポイント: GET /api/pro/signals/{symbol}?days={days}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - データ取得日数（デフォルト 200 日）
 * @returns {@link AISignalResult} オブジェクト
 */
export async function getProSignals(symbol: string, days = 200): Promise<import("@/types").AISignalResult> {
  return fetchAPI(`/api/pro/signals/${symbol}?days=${days}`);
}

/**
 * Pro プラン向けのマーケットブリーフ（ニュース・SNS・経済指標・AI サマリー）を取得する。
 *
 * エンドポイント: GET /api/pro/market-brief/{symbol}
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link MarketBrief} オブジェクト
 */
export async function getProMarketBrief(symbol: string): Promise<import("@/types").MarketBrief> {
  return fetchAPI(`/api/pro/market-brief/${symbol}`);
}

/**
 * Pro プラン向けのトレードコーチング（過去取引統計 + AI アドバイス）を取得する。
 *
 * エンドポイント: GET /api/pro/coaching/{symbol}
 *
 * @param symbol - 通貨ペアシンボル
 * @returns {@link CoachingResult} オブジェクト
 */
export async function getProCoaching(symbol: string): Promise<import("@/types").CoachingResult> {
  return fetchAPI(`/api/pro/coaching/${symbol}`);
}

/**
 * Pro プラン向けの統合バックテスト（シンプル・Backtrader・ウォークフォワード）を取得する。
 *
 * エンドポイント: GET /api/pro/backtest/{symbol}?days={days}
 *
 * @param symbol - 通貨ペアシンボル
 * @param days - バックテスト期間（日数）（デフォルト 200 日）
 * @returns シンプル・Backtrader・ウォークフォワードの 3 種類のバックテスト結果
 */
export async function getProBacktest(symbol: string, days = 200): Promise<{
  symbol: string;
  simple: SignalBacktest;
  backtrader: BacktraderResult;
  walk_forward: WalkForwardResult;
}> {
  return fetchAPI(`/api/pro/backtest/${symbol}?days=${days}`);
}

/**
 * Pro プラン向けの高度なリスク分析（ドローダウン・資本配分・リスクバジェット）を取得する。
 *
 * エンドポイント: GET /api/pro/risk/{symbol}?account_balance=...&risk_percent=...
 *
 * @param symbol - 通貨ペアシンボル
 * @param accountBalance - 口座残高（USD）（デフォルト 10,000 USD）
 * @param riskPercent - 1 トレードあたりのリスク率（%）（デフォルト 1%）
 * @returns {@link AdvancedRisk} オブジェクト
 */
export async function getProRisk(
  symbol: string,
  accountBalance = 10000,
  riskPercent = 1
): Promise<import("@/types").AdvancedRisk> {
  return fetchAPI(`/api/pro/risk/${symbol}?account_balance=${accountBalance}&risk_percent=${riskPercent}`);
}

/**
 * Pro プラン向けのポートフォリオ概要（複数口座・通貨ペア・直近注文）を取得する。
 *
 * エンドポイント: GET /api/pro/portfolio
 *
 * @returns {@link PortfolioOverview} オブジェクト
 */
export async function getProPortfolio(): Promise<import("@/types").PortfolioOverview> {
  return fetchAPI("/api/pro/portfolio");
}

/**
 * Pro プラン向けの AI チャットにメッセージを送信して返答を受け取る。
 *
 * エンドポイント: POST /api/pro/chat
 * リクエストボディ: `{ message, symbol, session_id }`
 * セッション ID を渡すことで会話履歴が維持される。
 *
 * @param message - ユーザーのチャットメッセージ
 * @param symbol - 現在選択中の通貨ペアシンボル（コンテキストとして使用）
 * @param sessionId - 既存のチャットセッション ID（新規の場合は省略）
 * @returns {@link ChatResponse} オブジェクト（AI の返答・セッション ID・履歴を含む）
 */
export async function sendProChat(
  message: string,
  symbol: string,
  sessionId?: number
): Promise<import("@/types").ChatResponse> {
  return fetchAPI("/api/pro/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, symbol, session_id: sessionId ?? null }),
  });
}

/**
 * 自動売買の設定とデフォルト値を取得する。
 *
 * エンドポイント: GET /api/autotrade/config
 *
 * @returns 現在の設定（`config`）とシステムデフォルト設定（`defaults`）
 */
export async function getAutoTradeConfig(): Promise<{
  config: import("@/types").AutoTradeConfig;
  defaults: import("@/types").AutoTradeConfig;
}> {
  return fetchAPI("/api/autotrade/config");
}

/**
 * 自動売買の設定を部分更新する。
 *
 * エンドポイント: PUT /api/autotrade/config
 * リクエストボディ: {@link AutoTradeConfig} の部分オブジェクト
 *
 * @param config - 更新する設定項目
 * @returns 更新後の完全な設定オブジェクト
 */
export async function updateAutoTradeConfig(
  config: Partial<import("@/types").AutoTradeConfig>
): Promise<{ config: import("@/types").AutoTradeConfig }> {
  return fetchAPI("/api/autotrade/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

/**
 * 自動売買システムの現在の稼働状況を取得する。
 *
 * エンドポイント: GET /api/autotrade/status
 * スケジューラーの状態・直近の実行履歴・パフォーマンス統計が含まれる。
 *
 * @returns {@link AutoTradeStatus} オブジェクト
 */
export async function getAutoTradeStatus(): Promise<import("@/types").AutoTradeStatus> {
  return fetchAPI("/api/autotrade/status");
}

/**
 * 自動売買の実行ログ一覧を取得する。
 *
 * エンドポイント: GET /api/autotrade/runs?limit={limit}[&symbol={symbol}]
 *
 * @param symbol - フィルタするシンボル（省略時は全シンボル）
 * @param limit - 取得件数上限（デフォルト 30 件）
 * @returns 実行ログの配列を含むオブジェクト
 */
export async function getAutoTradeRuns(
  symbol?: string,
  limit = 30
): Promise<{ runs: import("@/types").AutoTradeRun[] }> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  return fetchAPI(`/api/autotrade/runs?${q}`);
}

/**
 * 指定シンボルの自動売買シグナルを評価してトレード判断を返す（実際には発注しない）。
 *
 * エンドポイント: POST /api/autotrade/evaluate/{symbol}
 * 設定が `paper` / `live` どちらであっても発注は行われない評価専用エンドポイント。
 *
 * @param symbol - 評価対象の通貨ペアシンボル
 * @returns {@link AutoTradeEvaluateResult} オブジェクト（判断・理由・シグナルスナップショット）
 */
export async function evaluateAutoTrade(
  symbol: string
): Promise<import("@/types").AutoTradeEvaluateResult> {
  return fetchAPI(`/api/autotrade/evaluate/${symbol}`, { method: "POST" });
}

/**
 * 指定シンボルの自動売買を即時実行する（設定が live の場合は実際に発注される）。
 *
 * エンドポイント: POST /api/autotrade/run/{symbol}
 *
 * @param symbol - 実行対象の通貨ペアシンボル
 * @returns 実行結果（{@link AutoTradeEvaluateResult}）
 */
export async function runAutoTradeSymbol(
  symbol: string
): Promise<import("@/types").AutoTradeEvaluateResult> {
  return fetchAPI(`/api/autotrade/run/${symbol}`, { method: "POST" });
}

/**
 * 設定された全シンボルに対して自動売買を一括実行する。
 *
 * エンドポイント: POST /api/autotrade/run
 *
 * @returns 実行結果の配列と件数
 */
export async function runAutoTradeAll(): Promise<{
  results: import("@/types").AutoTradeRun[];
  count: number;
}> {
  return fetchAPI("/api/autotrade/run", { method: "POST" });
}

/**
 * 自動売買のプリセット一覧を取得する。
 *
 * エンドポイント: GET /api/autotrade/presets
 * 保守的・標準・積極的などのプリセット設定が含まれる。
 *
 * @returns プリセットの配列を含むオブジェクト
 */
export async function getAutoTradePresets(): Promise<{ presets: import("@/types").AutoTradePreset[] }> {
  return fetchAPI("/api/autotrade/presets");
}

/**
 * 指定したプリセットを現在の自動売買設定に適用する。
 *
 * エンドポイント: POST /api/autotrade/presets/apply
 * リクエストボディ: `{ preset_id }`
 *
 * @param presetId - 適用するプリセットの ID
 * @returns 適用後の設定オブジェクト
 */
export async function applyAutoTradePreset(presetId: string): Promise<{ config: import("@/types").AutoTradeConfig }> {
  return fetchAPI("/api/autotrade/presets/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preset_id: presetId }),
  });
}

/**
 * ユーザーの投資スタイル・リスク嗜好に基づいて最適なプリセットを AI が自動選択する。
 *
 * エンドポイント: POST /api/autotrade/autoselect
 * リクエストボディ: `{ capital, horizon, risk_appetite, style, apply, preferred_symbols }`
 * `apply: true` を指定すると選択されたプリセットが自動的に適用される。
 *
 * @param opts - 選択条件（資本規模・投資期間・リスク嗜好・スタイル・自動適用フラグ）
 * @returns 推奨プリセット ID・ラベル・設定・選定理由
 */
export async function autoSelectAutoTrade(opts: {
  capital?: string;
  horizon?: string;
  risk_appetite?: string;
  style?: string;
  apply?: boolean;
}): Promise<{ recommended_preset: string; preset_label: string; config: import("@/types").AutoTradeConfig; rationale: string }> {
  return fetchAPI("/api/autotrade/autoselect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...opts, preferred_symbols: null }),
  });
}

/**
 * 自動売買設定に基づくシミュレーション（バックテスト + 資本充足性評価）を実行する。
 *
 * エンドポイント: GET /api/autotrade/simulate/{symbol}?[days=...&account_balance=...&preset_id=...]
 *
 * @param symbol - シミュレーション対象の通貨ペアシンボル
 * @param opts - オプション（期間・口座残高・プリセット ID）
 * @returns {@link AutoTradeSimulation} オブジェクト（バックテスト結果・資本評価・総合判定）
 */
export async function simulateAutoTrade(
  symbol: string,
  opts: { days?: number; accountBalance?: number; presetId?: string } = {}
): Promise<import("@/types").AutoTradeSimulation> {
  const q = new URLSearchParams();
  if (opts.days) q.set("days", String(opts.days));
  if (opts.accountBalance) q.set("account_balance", String(opts.accountBalance));
  if (opts.presetId) q.set("preset_id", opts.presetId);
  return fetchAPI(`/api/autotrade/simulate/${symbol}?${q}`);
}
