import { NextRequest, NextResponse } from "next/server";

const INTERNAL_API =
  process.env.INTERNAL_API_URL ||
  (process.env.NODE_ENV === "production" ? "http://127.0.0.1:8000" : "http://localhost:8000");

const AI_TIMEOUT_MS = 120_000;

function forwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const auth = request.headers.get("authorization");
  if (auth) headers.set("authorization", auth);
  const apiKey = request.headers.get("x-api-key");
  if (apiKey) headers.set("x-api-key", apiKey);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  headers.set("accept", "application/json");
  return headers;
}

async function proxyToBackend(request: NextRequest, path: string[]) {
  const search = request.nextUrl.search;
  const target = `${INTERNAL_API}/api/ai/${path.join("/")}${search}`;

  try {
    const res = await fetch(target, {
      method: request.method,
      headers: forwardHeaders(request),
      cache: "no-store",
      signal: AbortSignal.timeout(AI_TIMEOUT_MS),
    });
    const contentType = res.headers.get("content-type") ?? "application/json";
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: { "Content-Type": contentType },
    });
  } catch (err) {
    const isTimeout =
      err instanceof Error &&
      (err.name === "TimeoutError" || err.name === "AbortError" || err.message.includes("timeout"));
    if (isTimeout) {
      return NextResponse.json(
        {
          detail:
            "AI分析がタイムアウトしました（120秒）。総合レポートタブを試すか、しばらく待って再実行してください。",
        },
        { status: 504 },
      );
    }
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

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return proxyToBackend(request, path);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  return proxyToBackend(request, path);
}
