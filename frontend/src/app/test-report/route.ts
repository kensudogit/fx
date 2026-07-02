/**
 * @file app/test-report/route.ts
 * @description テストレポート配信ルート
 *
 * pytest-html で生成した HTML テストレポートをブラウザから直接閲覧できるようにする
 * Next.js Route Handler。
 *
 * アクセス URL: https://<railway-domain>/test-report
 *
 * ファイルの場所 (Docker コンテナ内):
 *   /app/frontend/public/test-report/index.html
 *   ← Dockerfile でバックエンドの tests/report/test_report.html からコピー
 */

import { existsSync, readFileSync } from "fs";
import { NextResponse } from "next/server";
import { join } from "path";

export async function GET() {
  // Next.js 本番環境での process.cwd() = /app/frontend (Docker 内)
  const reportPath = join(
    process.cwd(),
    "public",
    "test-report",
    "index.html"
  );

  if (existsSync(reportPath)) {
    const html = readFileSync(reportPath, "utf-8");
    return new NextResponse(html, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache",
      },
    });
  }

  // レポートファイルが存在しない場合のフォールバックページ
  const fallback = `<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FX Platform - Test Report</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f172a; color: #e2e8f0;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }
    .card {
      background: #1e293b; border: 1px solid #334155; border-radius: 16px;
      padding: 48px 40px; max-width: 560px; width: 90%; text-align: center;
      box-shadow: 0 25px 50px rgba(0,0,0,0.5);
    }
    .icon { font-size: 64px; margin-bottom: 24px; }
    h1 { color: #38bdf8; font-size: 24px; margin-bottom: 12px; }
    p { color: #94a3b8; line-height: 1.6; margin-bottom: 16px; }
    code {
      background: #0f172a; padding: 16px 20px; border-radius: 8px;
      display: block; margin: 20px 0; font-size: 13px;
      border: 1px solid #475569; text-align: left; color: #7dd3fc;
      line-height: 1.8;
    }
    .badge {
      display: inline-block; background: #1d4ed8; color: #bfdbfe;
      padding: 4px 12px; border-radius: 20px; font-size: 12px; margin-bottom: 24px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">📊</div>
    <div class="badge">FX Platform</div>
    <h1>Test Report</h1>
    <p>テストレポートは次の Railway デプロイ後に自動生成されます。</p>
    <p>ローカルで今すぐ生成する場合:</p>
    <code>cd backend<br>run_presentation_tests.bat</code>
    <p style="font-size:13px; color:#64748b;">
      生成後は GitHub へコミット → Railway が自動デプロイ → このページでレポートが表示されます。
    </p>
  </div>
</body>
</html>`;

  return new NextResponse(fallback, {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
