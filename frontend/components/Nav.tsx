"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS: { href: string; label: string; desc: string }[] = [
  { href: "/", label: "Overview", desc: "health & counts" },
  { href: "/live", label: "Live Markets", desc: "5m / 15m up/down" },
  { href: "/wallet", label: "Wallet Analysis", desc: "PnL forensics" },
  { href: "/strategy", label: "Strategy Lab", desc: "backtest vs random" },
  { href: "/paper", label: "Paper Trading", desc: "live latency sim" },
  { href: "/data-quality", label: "Data Quality", desc: "feeds & gaps" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  // /replay/[id] is a sub-view of Live Markets
  if (href === "/live") return pathname.startsWith("/live") || pathname.startsWith("/replay");
  return pathname.startsWith(href);
}

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5 p-3">
      {LINKS.map((l) => {
        const active = isActive(pathname, l.href);
        return (
          <Link
            key={l.href}
            href={l.href}
            className={`group rounded-md px-3 py-2 transition-colors ${
              active
                ? "bg-surface-2 text-foreground"
                : "text-muted hover:bg-surface-2/60 hover:text-foreground"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  active ? "bg-accent" : "bg-border group-hover:bg-muted"
                }`}
              />
              <span className="text-sm font-medium">{l.label}</span>
            </div>
            <div className="ml-3.5 text-[11px] text-muted">{l.desc}</div>
          </Link>
        );
      })}
    </nav>
  );
}
