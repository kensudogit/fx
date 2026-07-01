/**
 * @file auth.ts
 * @description フロントエンドの認証トークン管理モジュール。
 *
 * JWT アクセストークンと API キーの読み書き・削除・HTTP ヘッダー生成を担う。
 * - JWT トークンは `localStorage` に永続保存し、同時に Cookie にも書き込む。
 *   Cookie は Next.js Middleware のルート保護で使用される（サーバーサイドで読める）。
 * - API キーは `localStorage` のみに保存する（Cookie には書かない）。
 * - `authHeaders()` は API リクエスト時に呼び出され、トークンの種類に応じて
 *   `Authorization: Bearer <token>` または `X-API-Key: <key>` ヘッダーを返す。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

/** localStorage に JWT アクセストークンを保存するキー名 */
const TOKEN_KEY = "fx_access_token";

/** localStorage に API キーを保存するキー名 */
const API_KEY_KEY = "fx_api_key";

/**
 * localStorage から JWT アクセストークンを取得する。
 *
 * サーバーサイドレンダリング時（`window` が未定義）は `null` を返す。
 *
 * @returns JWT アクセストークン文字列、未ログインまたは SSR 時は `null`
 */
export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * JWT アクセストークンを localStorage と Cookie の両方に保存する。
 *
 * Cookie の設定:
 * - `path=/` — サイト全体で有効
 * - `max-age=259200`（72 時間）— セッション有効期限
 * - `SameSite=Lax` — CSRF 対策（外部サイトからのリクエストでは送信されない）
 * - `HttpOnly` は付与しない（クライアント JS からも読む必要があるため）
 *
 * @param token - 保存する JWT アクセストークン文字列
 */
export function setAccessToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  // Next.js Middleware がサーバーサイドで認証チェックできるよう Cookie にも保存する
  document.cookie = `fx_access_token=${encodeURIComponent(token)}; path=/; max-age=${72 * 3600}; SameSite=Lax`;
}

/**
 * localStorage から API キーを取得する。
 *
 * サーバーサイドレンダリング時（`window` が未定義）は `null` を返す。
 *
 * @returns API キー文字列、未設定または SSR 時は `null`
 */
export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(API_KEY_KEY);
}

/**
 * API キーを localStorage に保存する。
 *
 * JWT トークンと異なり、Cookie には保存しない。
 * API キーは主に非 SaaS モードでの認証に使用される。
 *
 * @param key - 保存する API キー文字列
 */
export function setApiKey(key: string) {
  localStorage.setItem(API_KEY_KEY, key);
}

/**
 * 認証情報（JWT トークン・API キー）をすべてクリアする。
 *
 * ログアウト時や 401 エラー時に呼び出される。
 * localStorage のエントリを削除し、Cookie も `max-age=0` で即時無効化する。
 */
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(API_KEY_KEY);
  // Cookie を即時削除（max-age=0 で有効期限を過去に設定）
  document.cookie = "fx_access_token=; path=/; max-age=0";
}

/**
 * バックエンド API へのリクエストに付与する認証ヘッダーを生成する。
 *
 * 優先順位:
 * 1. JWT アクセストークンが存在する場合 → `Authorization: Bearer <token>`
 * 2. JWT がなく API キーが存在する場合 → `X-API-Key: <key>`
 * 3. どちらも存在しない場合 → 空オブジェクト（認証なし）
 *
 * @returns 認証ヘッダーのキー・値オブジェクト。`fetchAPI` 内で `headers` にスプレッドして使用する。
 */
export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  if (token) return { Authorization: `Bearer ${token}` };
  const apiKey = getApiKey();
  if (apiKey) return { "X-API-Key": apiKey };
  return {};
}

/**
 * SaaS モードが有効かどうかを示すフラグ。
 *
 * 環境変数 `NEXT_PUBLIC_SAAS_ENABLED` が `"false"` の場合のみ無効（セルフホスト向け）。
 * 未設定の場合はデフォルトで `true`（SaaS モード有効）として動作する。
 *
 * このフラグが `true` の場合:
 * - ログイン・登録ページが有効になる
 * - 未認証ユーザーは Middleware によってリダイレクトされる
 * - 401 エラー時に自動ログアウトが行われる
 */
export const SAAS_ENABLED = process.env.NEXT_PUBLIC_SAAS_ENABLED !== "false";
