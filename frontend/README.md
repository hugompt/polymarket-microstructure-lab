# polymarket-microstructure-lab — frontend

Read-only research dashboard for analyzing Polymarket crypto **Up/Down** markets
and one target bot wallet. It **does not trade**. The tone is skeptical and
data-focused: balances are never presented as profit, win rate is shown next to
break-even win rate, and backtests are always compared to a random baseline.

Stack: Next.js (App Router) + TypeScript + Tailwind CSS + Recharts. No auth, no
wallet libraries, no web3 — every view is a plain GET/POST against the backend.

## Pages

| Route             | Purpose                                                              |
| ----------------- | ------------------------------------------------------------------- |
| `/`               | Overview — health, counts, feed status, warnings                    |
| `/live`           | Live 5m/15m markets, polled every 5s, with countdowns                |
| `/replay/[id]`    | Market replay — price/book/oracle charts + wallet-trade markers      |
| `/wallet`         | Wallet analysis — three distinct PnL figures, breakdowns, break-even |
| `/strategy`       | Strategy Lab — run a backtest, compare to random, browse past runs   |
| `/data-quality`   | Feed health, per-market gaps, totals, API error log                  |

## Develop

```bash
npm install
npm run dev          # http://localhost:3000
```

The dev server expects the backend at `NEXT_PUBLIC_API_BASE` (default
`http://localhost:8000`). Copy the example env if you need a different base:

```bash
cp .env.example .env.local
# edit NEXT_PUBLIC_API_BASE if your backend runs elsewhere
```

Every page renders graceful **loading / backend-down / empty** states, so the
dashboard works even before the collectors have written any data — you'll just
see "No data yet — run the collectors" placeholders.

## Build

```bash
npm run build        # production build (Next standalone output)
npm start            # serve the production build on :3000
```

## Docker

```bash
docker build -t pm-microstructure-frontend .
docker run --rm -p 3000:3000 \
  -e NEXT_PUBLIC_API_BASE=http://host.docker.internal:8000 \
  pm-microstructure-frontend
```

> Note: `NEXT_PUBLIC_*` values are inlined at **build** time. To point the image
> at a different backend, pass `--build-arg NEXT_PUBLIC_API_BASE=...` when
> building (the Dockerfile forwards it).

## Conventions

- All times are rendered in **UTC** and labelled as such.
- Prices are 0–1 probabilities; money is USDC.
- API client + typed fallbacks live in `lib/api.ts`; types mirror
  `docs/API_CONTRACT.md` in `lib/types.ts`.
- Reusable UI in `components/` (StatCard, StatusPill, DataTable, SectionCard,
  WarningPanel, chart wrappers).
