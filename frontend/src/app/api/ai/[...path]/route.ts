/**
 * @file app/api/ai/[...path]/route.ts
 * @description Next.js BFF（Backend for Frontend）プロキシルート — AI エンドポイント転送。
 *
 * `/api/ai/**` へのリクエストをバックエンド FastAPI サーバーの `/api/ai/**` へ
 * 透過的に転送するリバースプロキシ。
 *
 * このルートが存在する理由:
 * - AI 分析は処理時間が長く（最大 120 秒）、直接バックエンドを呼び出すと
 *   CORS や認証の問題が生じる可能性がある。
 * - Next.js の BFF 層を経由させることで、認証ヘッダーの転送・タイムアウト管理・
 *   エラーメッセージの日本語化を一箇所で行える。
 * - フロントエンドからは同一オリジンとして呼び出せるため、CORS の問題を回避できる。
 *
 * 転送するヘッダー:
 * - `Authorization` — JWT Bearer トークン
 * - `X-API-Key` — API キー認証
 * - `cookie` — セッション Cookie（必要な場合）
 *
 * エラーハンドリング:
 * - タイムアウト（120 秒超過）→ 504 ステータスと日本語メッセージを返す
 * - 接続エラー（バックエンド停止など）→ 502 ステータスと日本語メッセージを返す
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { NextRequest, NextResponse } from "next/server";

/**
 * バックエンド API サーバーの内部 URL。
 *
 * 優先順位:
 * 1. 環境変数 `INTERNAL_API_URL`（Railway・Docker 環境での内部通信用）
 * 2. 本番環境（`NODE_ENV === "production"`）→ `http://127.0.0.1:8000`（ローカルホスト）
 * 3. 開発環境 → `http://localhost:8000`
 */
const INTERNAL_API =
  process.env.INTERNAL_API_URL ||
  (process.env.NODE_ENV === "production" ? "http://127.0.0.1:8000" : "http://localhost:8000");

/**
 * AI エンドポイントのタイムアウト時間（ミリ秒）。
 *
 * OpenAI GPT の API 呼び出しを含む AI 分析は処理に時間がかかる。
 * 120 秒（2 分）を上限として、これを超えた場合は 504 エラーを返す。
 */
const AI_TIMEOUT_MS = 120_000;

/**
 * クライアントリクエストからバックエンドへ転送するヘッダーを生成する。
 *
 * セキュリティ上の理由から、すべてのヘッダーを転送するのではなく
 * 認証に必要なヘッダーのみを選択的に転送する。
 * - `authorization` — JWT Bearer トークン
 * - `x-api-key` — API キー認証
 * - `cookie` — セッション Cookie（必要な場合）
 * - `accept` — `application/json` を固定で設定
 *
 * @param request - クライアントから受け取った Next.js リクエストオブジェクト
 * @returns バックエンドへ転送するヘッダーオブジェクト
 */
function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  // JWT Bearer トークンを転送（存在する場合のみ）
  const auth = request.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  // API キーを転送（存在する場合のみ）
  const apiKey = request.headers.get("x-api-key");
  if (apiKey) headers.set("x-api-key", apiKey);
  // Cookie を転送（セッション管理が必要な場合）
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  // レスポンスとして JSON を要求する
  headers.set("accept", "application/json");
  return headers;
}

/**
 * リクエストをバックエンドの AI エンドポイントへ転送する共通処理。
 *
 * - `AbortSignal.timeout()` で 120 秒のタイムアウトを設定する。
 * - バックエンドのレスポンスをそのままクライアントへ返す（ステータスコード・Content-Type を保持）。
 * - タイムアウトエラーは 504、その他の接続エラーは 502 として返す。
 *
 * @param request - クライアントから受け取った Next.js リクエストオブジェクト
 * @param path - URL パスセグメントの配列（例: `["news", "USDJPY"]` → `/api/ai/news/USDJPY`）
 * @returns バックエンドのレスポンスを転送した Next.js レスポンス
 */
async function proxyToBackend(request: NextRequest, path: string[]) {
  // クエリパラメータを含む完全な転送先 URL を構築する
  const search = request.nextUrl.search;
  const target = `${INTERNAL_API}/api/ai/${path.join("/")}${search}`;

  try {
    const res = await fetch(target, {
      // クライアントと同じ HTTP メソッドを使用（GET / POST）
      method: request.method,
      // 認証ヘッダーを転送する
      headers: forwardHeaders(request),
      // キャッシュを無効化してバックエンドから常に最新データを取得する
      cache: "no-store",
      // 120 秒のタイムアウトを設定（AI 処理の最大待機時間）
      signal: AbortSignal.timeout(AI_TIMEOUT_MS),
    });

    // バックエンドの Content-Type をそのまま転送する（JSON・テキスト両対応）
    const contentType = res.headers.get("content-type") ?? "application/json";
    // レスポンスボディをテキストとして読み取る（バイナリや JSON を問わず対応）
    const body = await res.text();

    // バックエンドのステータスコード・Content-Type を維持してクライアントへ返す
    return new NextResponse(body, {
      status: res.status,
      headers: { "Content-Type": contentType },
    });
  } catch (err) {
    // タイムアウトエラーの検出（AbortError / TimeoutError / メッセージ内の "timeout"）
    const isTimeout =
      err instanceof Error &&
      (err.name === "TimeoutError" || err.name === "AbortError" || err.message.includes("timeout"));

    if (isTimeout) {
      // 120 秒タイムアウト → 504 Gateway Timeout として返す
      return NextResponse.json(
        {
          detail:
            "AI分析がタイムアウトしました（120秒）。総合レポートタブを試すか、しばらく待って再実行してください。",
        },
        { status: 504 },
      );
    }

    // 接続エラー（バックエンドが停止・Railway の再起動中など）→ 502 Bad Gateway として返す
    console.error("AI proxy error:", err);
    return NextResponse.json(
      {
        detail:
          "バックエンドに接続できません（502）。Railway の再デプロイ後に再試行するか、/health で API 状態を確認してください。",
      },
      { status: 502 },
    );
  }
}

/**
 * GET リクエストのハンドラー。
 *
 * `/api/ai/**` への GET リクエストをバックエンドへ転送する。
 * 主に AI 分析結果の取得（ニュース分析・リスク評価・トレード判断など）に使用される。
 *
 * @param request - クライアントから受け取った Next.js リクエストオブジェクト
 * @param context - Next.js が提供するルートコンテキスト（`params.path` にパスセグメント配列が入る）
 * @returns バックエンドのレスポンスを転送した Next.js レスポンス
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  // Next.js 15+ では params が Promise として提供される（await が必要）
  const { path } = await context.params;
  return proxyToBackend(request, path);
}

/**
 * POST リクエストのハンドラー。
 *
 * `/api/ai/**` への POST リクエストをバックエンドへ転送する。
 * 主に AI チャットへのメッセージ送信など、ボディを含むリクエストに使用される。
 *
 * @param request - クライアントから受け取った Next.js リクエストオブジェクト
 * @param context - Next.js が提供するルートコンテキスト（`params.path` にパスセグメント配列が入る）
 * @returns バックエンドのレスポンスを転送した Next.js レスポンス
 */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  // Next.js 15+ では params が Promise として提供される（await が必要）
  const { path } = await context.params;
  return proxyToBackend(request, path);
}
