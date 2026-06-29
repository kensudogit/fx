/**
 * フロントエンド共通ライブラリ — auth
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

const TOKEN_KEY = "fx_access_token";
const API_KEY_KEY = "fx_api_key";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  document.cookie = `fx_access_token=${encodeURIComponent(token)}; path=/; max-age=${72 * 3600}; SameSite=Lax`;
}

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_KEY);
}

export function setApiKey(key: string) {
  localStorage.setItem(API_KEY_KEY, key);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(API_KEY_KEY);
  document.cookie = "fx_access_token=; path=/; max-age=0";
}

export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  if (token) return { Authorization: `Bearer ${token}` };
  const apiKey = getApiKey();
  if (apiKey) return { "X-API-Key": apiKey };
  return {};
}

export const SAAS_ENABLED = process.env.NEXT_PUBLIC_SAAS_ENABLED !== "false";
