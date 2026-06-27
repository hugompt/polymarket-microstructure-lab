import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { API_BASE } from "@/lib/api";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Polymarket Microstructure Lab",
  description:
    "Read-only research dashboard for Polymarket crypto Up/Down markets and a target bot wallet. No trading.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-background text-foreground">
        <div className="flex min-h-screen">
          {/* Sidebar */}
          <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
            <Link href="/" className="block border-b border-border px-4 py-4">
              <div className="text-sm font-semibold leading-tight text-foreground">
                Polymarket
                <br />
                Microstructure Lab
              </div>
              <div className="mt-1 text-[11px] text-muted">
                crypto up/down · order-flow forensics
              </div>
            </Link>
            <Nav />
            <div className="mt-auto border-t border-border px-4 py-3">
              <div className="text-[11px] text-muted">API base</div>
              <code className="break-all text-[11px] text-muted/80">{API_BASE}</code>
            </div>
          </aside>

          {/* Main column */}
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/90 px-5 py-3 backdrop-blur">
              <div className="flex items-center gap-3">
                <Link
                  href="/"
                  className="text-sm font-semibold text-foreground md:hidden"
                >
                  PM Microstructure Lab
                </Link>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-md border border-warn/40 bg-warn/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-warn">
                  Read-only research — no trading
                </span>
              </div>
            </header>

            {/* Mobile nav row */}
            <div className="border-b border-border bg-surface px-2 md:hidden">
              <Nav />
            </div>

            <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
