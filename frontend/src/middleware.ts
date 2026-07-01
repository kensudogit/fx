/**
 * @file middleware.ts
 * @description Next.js Edge Middleware — ルート保護とリダイレクト処理。
 *
 * すべてのページリクエストをインターセプトし、認証が必要なルートへの
 * 未認証アクセスをログインページへリダイレクトする。
 *
 * 動作フロー:
 * 1. SaaS モードが無効（NEXT_PUBLIC_SAAS_ENABLED=false）の場合 → 全ルートを通過させる
 * 2. アクセスパスが PUBLIC_PATHS に含まれる場合 → 認証不要として通過させる
 * 3. Cookie `fx_access_token` が存在する場合 → 認証済みとして通過させる
 * 4. トークンがない場合 → `/login?from={元のパス}` へリダイレクトする
 *
 * `matcher` の設定により、静的ファイル（`_next/static`・画像・favicon）と
 * API ルートへのリクエストはミドルウェアをバイパスする。
 *
 * ※ トークンの有効性（署名・有効期限）はここでは検証しない。
 *   実際の認証検証はバックエンド API（JWT 検証）で行われる。
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * 認証なしでアクセス可能なパブリックパスの一覧。
 *
 * これらのパスおよびそのサブパス（例: `/login/callback`）は
 * 認証チェックをスキップする。
 * - `/login` — ログインページ
 * - `/register` — 新規登録ページ
 * - `/pricing` — プラン・料金ページ（未認証ユーザーへの案内用）
 */
const PUBLIC_PATHS = ["/login", "/register", "/pricing"];

/**
 * Next.js Edge Middleware のエントリーポイント。
 *
 * すべての対象リクエスト（`config.matcher` に一致するもの）に対して実行される。
 * Edge Runtime で動作するため、`localStorage` などのブラウザ API は使用できず、
 * 認証状態の確認は Cookie から行う。
 *
 * @param request - Next.js が提供するリクエストオブジェクト
 * @returns `NextResponse.next()` でリクエストを通過させるか、
 *          `NextResponse.redirect()` でログインページへリダイレクトする
 */
export function middleware(request: NextRequest) {
  // SaaS モードが無効（セルフホスト・開発環境など）の場合は全リクエストを通過させる
  const saasEnabled = process.env.NEXT_PUBLIC_SAAS_ENABLED !== "false";
  if (!saasEnabled) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;

  // パブリックパスへのアクセスは認証チェックをスキップする
  // startsWith でサブパス（例: /login?from=...）も一致させる
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  // Cookie から JWT アクセストークンを取得する
  // `setAccessToken` が Cookie に `fx_access_token` として書き込んでいる（lib/auth.ts 参照）
  const token = request.cookies.get("fx_access_token")?.value;

  if (!token) {
    // トークンが存在しない → 未認証としてログインページへリダイレクト
    // `from` パラメータにアクセス元のパスを渡し、ログイン後に元のページへ戻れるようにする
    const login = new URL("/login", request.url);
    login.searchParams.set("from", pathname);
    return NextResponse.redirect(login);
  }

  // トークンが存在する → 認証済みとしてリクエストを通過させる
  // トークンの有効性の詳細検証（署名・有効期限）はバックエンド API に委ねる
  return NextResponse.next();
}

/**
 * ミドルウェアを適用するルートのマッチャー設定。
 *
 * 以下のパスはミドルウェアをバイパスする（パフォーマンスと動作の正確性のため）:
 * - `_next/static` — Next.js のビルド済み静的アセット
 * - `_next/image` — Next.js の画像最適化エンドポイント
 * - `favicon.ico` — ファビコン
 * - `api` — バックエンドへのプロキシ API ルート（認証はバックエンド側で行う）
 */
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};
