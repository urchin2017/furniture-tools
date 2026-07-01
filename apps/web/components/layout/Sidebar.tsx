"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "首页" },
  { href: "/quote", label: "报价" },
  { href: "/drawings", label: "图纸" },
  { href: "/shipping-marks", label: "唛头" },
  { href: "/glossary", label: "术语表" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside className="w-56 shrink-0 bg-surface border-r border-border flex flex-col">
      <div className="h-14 flex items-center px-5 border-b border-border">
        <span className="font-semibold text-ink">家具工具</span>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`block rounded-lg px-3 py-2 text-sm transition-colors ${
              isActive(item.href)
                ? "bg-brand text-brand-ink"
                : "text-ink hover:bg-bg"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="p-3 text-xs text-muted border-t border-border">
        阶段 0 · 地基
      </div>
    </aside>
  );
}
