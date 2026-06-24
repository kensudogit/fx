const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...options });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
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
