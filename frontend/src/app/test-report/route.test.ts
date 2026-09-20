/**
 * @vitest-environment node
 *
 * @file app/test-report/route.test.ts
 * @description テストレポート配信 Route Handler のユニットテスト。
 *
 * Route Handler は `NextResponse` と Node の `fs` を使うため Node 環境で実行する。
 *
 * 検証範囲:
 * - レポート HTML が存在する場合にその中身を配信すること
 * - 参照するパスが `<cwd>/public/test-report/index.html` であること
 * - 配信時のヘッダー（Content-Type / Cache-Control）
 * - レポート未生成時に 200 でフォールバックページを返すこと
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { describe, it, expect, vi } from "vitest";
import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { GET } from "./route";

// fs をモックしてファイルシステムに依存しないテストにする
vi.mock("fs", () => ({
  existsSync: vi.fn(),
  readFileSync: vi.fn(),
}));

/** 想定されるレポートファイルのパス */
const reportPath = join(process.cwd(), "public", "test-report", "index.html");

describe("test-report — レポートが存在する場合", () => {
  it("レポート HTML の中身をそのまま返す", async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readFileSync).mockReturnValue("<html><body>pytest report</body></html>");

    const res = await GET();

    expect(res.status).toBe(200);
    await expect(res.text()).resolves.toContain("pytest report");
  });

  it("public/test-report/index.html を参照する", async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readFileSync).mockReturnValue("<html></html>");

    await GET();

    expect(existsSync).toHaveBeenCalledWith(reportPath);
    expect(readFileSync).toHaveBeenCalledWith(reportPath, "utf-8");
  });

  it("UTF-8 の HTML として、キャッシュ無効で配信する", async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readFileSync).mockReturnValue("<html></html>");

    const res = await GET();

    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(res.headers.get("Cache-Control")).toBe("no-cache");
  });
});

describe("test-report — レポートが存在しない場合", () => {
  it("ファイルを読まずにフォールバックページを返す", async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(readFileSync).mockClear();

    const res = await GET();

    expect(readFileSync).not.toHaveBeenCalled();
    expect(res.status).toBe(200);
  });

  it("フォールバックページに生成手順の案内を含む", async () => {
    vi.mocked(existsSync).mockReturnValue(false);

    const html = await (await GET()).text();

    expect(html).toContain("Test Report");
    expect(html).toContain("run_presentation_tests.bat");
    expect(html).toContain('<html lang="ja">');
  });

  it("フォールバックページも UTF-8 の HTML として配信する", async () => {
    vi.mocked(existsSync).mockReturnValue(false);

    const res = await GET();

    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
  });
});
