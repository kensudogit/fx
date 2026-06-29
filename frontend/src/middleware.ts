/**
 * フロントエンド — middleware
 *
 * FX トレード支援プラットフォーム（フロントエンド）
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/register", "/pricing"];

export function middleware(request: NextRequest) {
  const saasEnabled = process.env.NEXT_PUBLIC_SAAS_ENABLED !== "false";
  if (!saasEnabled) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  const token = request.cookies.get("fx_access_token")?.value;
  if (!token) {
    const login = new URL("/login", request.url);
    login.searchParams.set("from", pathname);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};
