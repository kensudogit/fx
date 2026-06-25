import { authHeaders } from "./auth";
import type { SignalBacktest, BacktraderResult, WalkForwardResult } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...options,
    headers: {
      ...authHeaders(),
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function getSymbols(): Promise<{ symbols: string[] }> {
  return fetchAPI("/api/symbols");
}

export async function getTechnicalAnalysis(
  symbol: string,
  days = 200
): Promise<import("@/types").TechnicalAnalysis> {
  return fetchAPI(`/api/technical/${symbol}?days=${days}`);
}

export async function getTradingSignals(
  symbol: string,
  days = 200
): Promise<{ symbol: string; signals: import("@/types").TradingSignal[]; price: number; source?: string }> {
  return fetchAPI(`/api/technical/${symbol}/signals?days=${days}`);
}

export async function getFundamentalData(
  eventType?: string
): Promise<import("@/types").FundamentalData> {
  const query = eventType ? `?event_type=${eventType}` : "";
  return fetchAPI(`/api/fundamental${query}`);
}

export async function getCalendar(): Promise<{ events: import("@/types").CalendarEvent[] }> {
  return fetchAPI("/api/fundamental/calendar");
}

export async function getMLPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").MLPrediction> {
  return fetchAPI(`/api/ml/predict/${symbol}?days=${days}`);
}

export async function syncMarketData(
  symbol: string,
  days = 200
): Promise<{ symbol: string; rows_synced: number; latest_close: number; latest_date: string }> {
  return fetchAPI(`/api/data/sync/${symbol}?days=${days}`, { method: "POST" });
}

export function getChartUrl(symbol: string, days = 200): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  return `${base}/api/chart/${symbol}?days=${days}`;
}

export const SOURCE_LABELS: Record<string, string> = {
  database: "PostgreSQL",
  yahoo_finance: "Yahoo Finance",
  sample: "サンプルデータ",
};

export async function getAIStatus(): Promise<{
  configured: boolean;
  model?: string;
  key_preview?: string | null;
}> {
  return fetchAPI("/api/ai/status");
}

export async function getAINews(symbol: string): Promise<import("@/types").AINewsAnalysis> {
  return fetchAPI(`/api/ai/news/${symbol}`);
}

export async function getAIFundamentalAnalysis(
  symbol: string
): Promise<import("@/types").AIFundamentalAnalysis> {
  return fetchAPI(`/api/ai/fundamental-analysis/${symbol}`);
}

export async function getAITradingDecision(
  symbol: string
): Promise<import("@/types").AITradingDecision> {
  return fetchAPI(`/api/ai/trading-decision/${symbol}`);
}

export async function getAIRisk(
  symbol: string,
  accountBalance = 10000
): Promise<import("@/types").AIRiskAssessment> {
  return fetchAPI(`/api/ai/risk/${symbol}?account_balance=${accountBalance}`);
}

export async function getAIReport(
  symbol: string,
  accountBalance = 10000
): Promise<import("@/types").AIFullReport> {
  return fetchAPI(`/api/ai/report/${symbol}?account_balance=${accountBalance}`);
}

export async function getMultiTimeframe(
  symbol: string
): Promise<import("@/types").MultiTimeframeAnalysis> {
  return fetchAPI(`/api/technical/${symbol}/multi-timeframe`);
}

export async function getSignalBacktest(
  symbol: string,
  days = 200
): Promise<import("@/types").SignalBacktest> {
  return fetchAPI(`/api/technical/${symbol}/backtest?days=${days}`);
}

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

export async function getEventAlerts(
  hours = 48
): Promise<{ alerts: import("@/types").EventAlert[]; within_hours: number }> {
  return fetchAPI(`/api/fundamental/alerts?hours=${hours}`);
}

export async function getDashboard(
  symbol: string,
  days = 200
): Promise<import("@/types").DashboardData> {
  return fetchAPI(`/api/dashboard?symbol=${symbol}&days=${days}`);
}

export async function getTradingViewSignals(
  symbol?: string,
  limit = 20
): Promise<{ signals: import("@/types").TradingViewSignal[] }> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  return fetchAPI(`/api/tradingview/signals?${q}`);
}

export async function getNewsAnalysis(
  symbol: string,
  limit = 8
): Promise<import("@/types").NewsAnalysisResult> {
  return fetchAPI(`/api/news/analysis/${symbol}?limit=${limit}`);
}

export async function getBacktraderBacktest(
  symbol: string,
  days = 200,
  cash = 10000
): Promise<import("@/types").BacktraderResult> {
  return fetchAPI(`/api/backtest/backtrader/${symbol}?days=${days}&cash=${cash}`);
}

export async function getOandaStatus(): Promise<import("@/types").OandaStatus> {
  return fetchAPI("/api/oanda/status");
}

export async function getOandaOrders(
  limit = 20
): Promise<{ orders: import("@/types").BrokerOrder[] }> {
  return fetchAPI(`/api/oanda/orders?limit=${limit}`);
}

export async function placeOandaOrder(
  symbol: string,
  side: "buy" | "sell",
  units: number
): Promise<import("@/types").BrokerOrder> {
  const q = new URLSearchParams({ symbol, side, units: String(units) });
  return fetchAPI(`/api/oanda/orders?${q}`, { method: "POST" });
}

export async function getTrendPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").TrendPrediction> {
  return fetchAPI(`/api/analysis/trend/${symbol}?days=${days}`);
}

export async function getAnalysisNews(
  symbol: string,
  limit = 8
): Promise<import("@/types").NewsAnalysisResult> {
  return fetchAPI(`/api/analysis/news/${symbol}?limit=${limit}`);
}

export async function getSNSAnalysis(
  symbol: string,
  limit = 10
): Promise<import("@/types").SNSAnalysis> {
  return fetchAPI(`/api/analysis/sns/${symbol}?limit=${limit}`);
}

export async function getEconomicAnalysis(
  symbol: string
): Promise<import("@/types").EconomicAnalysis> {
  return fetchAPI(`/api/analysis/economic/${symbol}`);
}

export async function getVolatilityPrediction(
  symbol: string,
  days = 200
): Promise<import("@/types").VolatilityPrediction> {
  return fetchAPI(`/api/analysis/volatility/${symbol}?days=${days}`);
}

export async function getIntelligenceReport(
  symbol: string,
  days = 200
): Promise<import("@/types").IntelligenceReport> {
  return fetchAPI(`/api/analysis/intelligence/${symbol}?days=${days}`);
}

export interface AuthSession {
  user: { id: number; email: string; role: string; tenant_id: number };
  tenant: { id: number; name: string; slug: string; plan: string };
  usage: { daily_calls: number; daily_limit: number; remaining: number };
  features: Record<string, boolean | number>;
}

export interface BillingPlan {
  id: string;
  name: string;
  price_monthly_usd: number;
  daily_api_limit: number;
  features: Record<string, boolean | number>;
}

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

export async function authMe(): Promise<AuthSession> {
  return fetchAPI("/api/auth/me");
}

export async function getBillingPlans(): Promise<{ plans: BillingPlan[]; saas_enabled: boolean }> {
  return fetchAPI("/api/billing/plans");
}

export async function upgradePlan(plan: string): Promise<{ tenant: AuthSession["tenant"] }> {
  return fetchAPI("/api/billing/upgrade", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan }),
  });
}

export async function listApiKeys(): Promise<{
  keys: { id: number; name: string; key_prefix: string; created_at: string | null }[];
}> {
  return fetchAPI("/api/auth/api-keys");
}

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

export async function getProSignals(symbol: string, days = 200): Promise<import("@/types").AISignalResult> {
  return fetchAPI(`/api/pro/signals/${symbol}?days=${days}`);
}

export async function getProMarketBrief(symbol: string): Promise<import("@/types").MarketBrief> {
  return fetchAPI(`/api/pro/market-brief/${symbol}`);
}

export async function getProCoaching(symbol: string): Promise<import("@/types").CoachingResult> {
  return fetchAPI(`/api/pro/coaching/${symbol}`);
}

export async function getProBacktest(symbol: string, days = 200): Promise<{
  symbol: string;
  simple: SignalBacktest;
  backtrader: BacktraderResult;
  walk_forward: WalkForwardResult;
}> {
  return fetchAPI(`/api/pro/backtest/${symbol}?days=${days}`);
}

export async function getProRisk(
  symbol: string,
  accountBalance = 10000,
  riskPercent = 1
): Promise<import("@/types").AdvancedRisk> {
  return fetchAPI(`/api/pro/risk/${symbol}?account_balance=${accountBalance}&risk_percent=${riskPercent}`);
}

export async function getProPortfolio(): Promise<import("@/types").PortfolioOverview> {
  return fetchAPI("/api/pro/portfolio");
}

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

export async function getAutoTradeConfig(): Promise<{
  config: import("@/types").AutoTradeConfig;
  defaults: import("@/types").AutoTradeConfig;
}> {
  return fetchAPI("/api/autotrade/config");
}

export async function updateAutoTradeConfig(
  config: Partial<import("@/types").AutoTradeConfig>
): Promise<{ config: import("@/types").AutoTradeConfig }> {
  return fetchAPI("/api/autotrade/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function getAutoTradeStatus(): Promise<import("@/types").AutoTradeStatus> {
  return fetchAPI("/api/autotrade/status");
}

export async function getAutoTradeRuns(
  symbol?: string,
  limit = 30
): Promise<{ runs: import("@/types").AutoTradeRun[] }> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (symbol) q.set("symbol", symbol);
  return fetchAPI(`/api/autotrade/runs?${q}`);
}

export async function evaluateAutoTrade(
  symbol: string
): Promise<import("@/types").AutoTradeEvaluateResult> {
  return fetchAPI(`/api/autotrade/evaluate/${symbol}`, { method: "POST" });
}

export async function runAutoTradeSymbol(
  symbol: string
): Promise<import("@/types").AutoTradeEvaluateResult> {
  return fetchAPI(`/api/autotrade/run/${symbol}`, { method: "POST" });
}

export async function runAutoTradeAll(): Promise<{
  results: import("@/types").AutoTradeRun[];
  count: number;
}> {
  return fetchAPI("/api/autotrade/run", { method: "POST" });
}
