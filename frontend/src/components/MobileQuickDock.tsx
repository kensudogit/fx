"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const DOCK_LINKS = [
  { href: "/", label: "分析", short: "FX" },
  { href: "/analysis", label: "総合", short: "5" },
  { href: "/autotrade", label: "自動", short: "⚡" },
  { href: "/ai", label: "AI", short: "AI" },
  { href: "/settings", label: "設定", short: "⚙" },
] as const;

export function MobileQuickDock() {
  const pathname = usePathname();

  return (
    <nav className="mobile-quick-dock" aria-label="クイックナビ">
      {DOCK_LINKS.map((link) => {
        const active = pathname === link.href || (link.href !== "/" && pathname.startsWith(link.href));
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`mobile-dock-item${active ? " is-active" : ""}`}
          >
            <span className="mobile-dock-icon">{link.short}</span>
            <span className="mobile-dock-label">{link.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
