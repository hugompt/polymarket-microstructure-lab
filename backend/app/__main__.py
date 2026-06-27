"""CLI entrypoint: ``python -m app <command>``.

Commands (all read-only):
  init-db        create the schema (SQLite quick-start; use Alembic for Postgres)
  discover       discover crypto Up/Down markets
  collect        run the live microstructure collector
  sync-wallet    fetch a wallet's public trades/activity/positions
  analyze-wallet backfill markets, enrich trades, print skeptical PnL analysis
  backtest       run a strategy simulation over RESOLVED markets (historical)
  paper-trade    FORWARD paper trade LIVE markets across latency accounts (SIMULATION, no orders)
  replay         summarise a market's replay series (optionally export CSV)
  export         export wallet-trades / market-replay / strategy-run as CSV
  serve          run the FastAPI server (uvicorn)
"""
from __future__ import annotations

import argparse
import sys

from .config import settings
from .cli import commands as c


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app", description="polymarket-microstructure-lab (read-only)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create database schema").set_defaults(func=c.cmd_init_db)

    d = sub.add_parser("discover", help="discover crypto Up/Down markets")
    d.add_argument("--no-closed", action="store_true", help="skip recently-closed markets")
    d.add_argument("--max-pages", type=int, default=10)
    d.add_argument("--max-pages-closed", type=int, default=3)
    d.set_defaults(func=c.cmd_discover)

    col = sub.add_parser("collect", help="run the live microstructure collector")
    col.add_argument("--assets", default=None, help="e.g. BTC,ETH,SOL,XRP,DOGE")
    col.add_argument("--windows", default=None, help="e.g. 5,15")
    col.add_argument("--duration", type=float, default=None, help="seconds (default: until Ctrl-C)")
    col.add_argument("--connections", type=int, default=None, help="max WS connections (default conservative)")
    col.add_argument("--no-ws", action="store_true", help="disable websockets (REST poll only)")
    col.add_argument("--no-poll", action="store_true", help="disable REST /book polling validator")
    col.set_defaults(func=c.cmd_collect)

    sw = sub.add_parser("sync-wallet", help="fetch a wallet's public history")
    sw.add_argument("--wallet", default=settings.target_wallet)
    sw.add_argument("--max-pages", type=int, default=50)
    sw.set_defaults(func=c.cmd_sync_wallet)

    aw = sub.add_parser("analyze-wallet", help="skeptical wallet PnL analysis")
    aw.add_argument("--wallet", default=settings.target_wallet)
    aw.add_argument("--scenario", default="conservative",
                    choices=["maker_like", "taker_like", "conservative", "none"])
    aw.add_argument("--no-backfill", action="store_true", help="skip fetching traded markets")
    aw.add_argument("--re-enrich", action="store_true",
                    help="force full re-enrichment over the network (slow; default reuses cache)")
    aw.add_argument("--max-markets", type=int, default=2000)
    aw.add_argument("--json", action="store_true", help="print full JSON")
    aw.set_defaults(func=c.cmd_analyze_wallet)

    bt = sub.add_parser("backtest", help="run a paper-trading strategy")
    bt.add_argument("--strategy", required=True)
    bt.add_argument("--assets", default=None)
    bt.add_argument("--windows", default=None)
    bt.add_argument("--latency", type=int, default=100, help="ms")
    bt.add_argument("--fill-model", default="realistic",
                    choices=["taker", "maker", "optimistic", "realistic", "conservative"])
    bt.add_argument("--fee-scenario", default="conservative",
                    choices=["maker_like", "taker_like", "conservative", "none"])
    bt.add_argument("--size", type=float, default=100.0)
    bt.add_argument("--date-from", default=None)
    bt.add_argument("--date-to", default=None)
    bt.add_argument("--params", default=None, help="JSON strategy params")
    bt.add_argument("--no-random", action="store_true", help="skip random baseline comparison")
    bt.add_argument("--no-persist", action="store_true")
    bt.set_defaults(func=c.cmd_backtest)

    rp = sub.add_parser("replay", help="summarise a market replay")
    rp.add_argument("--market", required=True, help="market id or slug")
    rp.add_argument("--csv", default=None, help="write replay CSV to this path")
    rp.add_argument("--no-fetch", action="store_true", help="DB-only (no CLOB history fetch)")
    rp.set_defaults(func=c.cmd_replay)

    ex = sub.add_parser("export", help="export CSV")
    ex.add_argument("--type", required=True,
                    choices=["wallet-trades", "market-replay", "strategy-run"])
    ex.add_argument("--wallet", default=None)
    ex.add_argument("--market", default=None)
    ex.add_argument("--run-id", default=None)
    ex.add_argument("--out", default=None, help="output path (default stdout)")
    ex.set_defaults(func=c.cmd_export)

    pt = sub.add_parser("paper-trade", help="FORWARD paper trade live markets (SIMULATION, no orders)")
    pt.add_argument("--strategy", default="stale_odds",
                    help="stale_odds|momentum|mean_reversion|divergence|orderbook_imbalance|"
                         "buy_favorite|always_up|always_down|random")
    pt.add_argument("--assets", default=None)
    pt.add_argument("--windows", default=None)
    pt.add_argument("--latencies", default="0,40,100,250,500,1000", help="ms grid (comma-sep)")
    pt.add_argument("--size", type=float, default=100.0)
    pt.add_argument("--duration", type=float, default=1800.0, help="seconds (default 30min)")
    pt.add_argument("--lookback", type=float, default=20.0, help="signal lookback seconds")
    pt.add_argument("--fee-scenario", default="conservative",
                    choices=["maker_like", "taker_like", "conservative", "none"])
    pt.add_argument("--params", default=None, help="JSON strategy params")
    pt.set_defaults(func=c.cmd_paper_trade)

    sv = sub.add_parser("serve", help="run the API server")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=c.cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    c.configure()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
