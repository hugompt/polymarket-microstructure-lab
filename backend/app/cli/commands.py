"""CLI command implementations. Read-only research only — none of these can trade."""
from __future__ import annotations

import asyncio
import json
import sys

from ..analysis.wallet import analyze_wallet
from ..config import settings
from ..db.base import Base
from ..db.session import engine, session_scope
from ..logging_conf import configure_logging, get_logger
from ..services.discovery import backfill_markets_for_wallet, run_discovery
from ..services.enrichment import enrich_wallet
from ..services.export import market_replay_csv, strategy_run_csv, wallet_trades_csv
from ..services.replay import build_replay
from ..services.wallet_sync import sync_wallet
from ..strategies.simulator import run_backtest
from ..util.timeutil import parse_any_time

log = get_logger("cli")


def _assets(s: str | None) -> list[str] | None:
    if not s:
        return None
    return [a.strip().upper() for a in s.split(",") if a.strip()]


def _windows(s: str | None) -> list[int] | None:
    if not s:
        return None
    return [int(x.strip().replace("m", "")) for x in s.split(",") if x.strip()]


def cmd_init_db(args) -> int:
    Base.metadata.create_all(bind=engine)
    print(f"Schema created on {settings.database_url}")
    print("(For production use Alembic: `alembic upgrade head`.)")
    return 0


def cmd_discover(args) -> int:
    summary = asyncio.run(run_discovery(
        include_closed=not args.no_closed,
        max_pages_open=args.max_pages, max_pages_closed=args.max_pages_closed))
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_collect(args) -> int:
    from ..services.collector import run_collector
    print(f"Collecting (assets={_assets(args.assets) or settings.assets}, "
          f"windows={_windows(args.windows) or settings.windows_minutes}, "
          f"duration={args.duration or 'until Ctrl-C'}). Read-only. Ctrl-C to stop.")
    try:
        summary = asyncio.run(run_collector(
            assets=_assets(args.assets), windows=_windows(args.windows),
            duration=args.duration, use_ws=not args.no_ws, use_rest_poll=not args.no_poll,
            max_connections=args.connections))
    except KeyboardInterrupt:
        print("\nstopped")
        return 0
    print(json.dumps({"tokens": summary["tokens"]}, indent=2, default=str))
    return 0


def _require_wallet(wallet: str) -> bool:
    if not wallet:
        print("error: no target wallet set. Pass --wallet 0x... or set PML_TARGET_WALLET in "
              "your .env (a PUBLIC on-chain address, never a private key).", file=sys.stderr)
        return False
    return True


def cmd_sync_wallet(args) -> int:
    wallet = args.wallet or settings.target_wallet
    if not _require_wallet(wallet):
        return 2
    summary = asyncio.run(sync_wallet(wallet, max_pages=args.max_pages))
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_analyze_wallet(args) -> int:
    wallet = args.wallet or settings.target_wallet
    if not _require_wallet(wallet):
        return 2
    if not args.no_backfill:
        bf = asyncio.run(backfill_markets_for_wallet(wallet, max_markets=args.max_markets))
        log.info("backfill", **{k: bf[k] for k in ("requested", "total", "new")})
    # only_missing=True keeps repeated runs fast and offline: trades already enriched are skipped.
    # Pass --re-enrich to force a full re-fetch (refetches resolution for every trade, slow).
    enr = enrich_wallet(wallet, scenario=args.scenario, only_missing=not args.re_enrich)
    log.info("enrich", **enr)
    with session_scope() as db:
        a = analyze_wallet(db, wallet, scenario=args.scenario)
    if args.json:
        print(json.dumps(a, indent=2, default=str))
        return 0
    _print_wallet_report(a)
    return 0


def _print_wallet_report(a: dict) -> None:
    acc, st, cov = a["accounting"], a["stats"], a["coverage"]
    print("=" * 78)
    print(f"WALLET {a['address']}  profile={a['profile'].get('name')!r} "
          f"({a['profile'].get('pseudonym')!r})")
    print("=" * 78)
    print("ACCOUNTING (these are DIFFERENT things — never conflate them):")
    print(f"  Reported realized PnL (API snapshot) : {acc['reported_realized_pnl']:>12.2f}")
    print(f"  Reconstructed PnL (gross)            : {acc['reconstructed_pnl']:>12.2f}")
    print(f"  Estimated PnL after fees ({acc['fee_scenario']:<12}): {acc['estimated_pnl_after_fees']:>12.2f}")
    print(f"  Estimated fees paid                  : {acc['estimated_fees']:>12.2f}")
    print(f"  Portfolio value (NOT profit)         : {acc['portfolio_value']:>12.2f}")
    print(f"  Total volume                         : {acc['total_volume']:>12.2f}")
    print(f"  Rewards/rebates                      : {acc['rewards']}")
    print(f"\nSTATS: n_trades={st['n_trades']} resolved={st['n_resolved_buy_trades']} "
          f"win_rate={_pct(st['win_rate'])} avg_entry={st['avg_entry_price']} "
          f"profit_factor={st['profit_factor']} max_dd={st['max_drawdown']}")
    print(f"COVERAGE: {cov['resolution_coverage_pct']}% "
          f"({cov['n_resolved_buy_trades']}/{cov['n_trades']} trades, "
          f"{cov['n_resolved_markets']} resolved markets)")
    print("\nSKEPTIC NOTES:")
    for n in a["skeptic_notes"]:
        print(f"  • {n}")
    if a["warnings"]:
        print("\nWARNINGS:")
        for w in a["warnings"]:
            print(f"  ! {w}")
    print("\nBREAK-EVEN vs ACTUAL by entry-price bucket (edge<0 = losing zone):")
    print(f"  {'bucket':<8}{'n':>6}{'avg_entry':>11}{'breakeven':>11}{'actual':>9}{'edge':>9}")
    for b in a["breakdowns"]["breakeven_by_bucket"]:
        print(f"  {b['bucket']:<8}{b['n']:>6}{_f(b['avg_entry']):>11}{_f(b['breakeven_winrate']):>11}"
              f"{_f(b['actual_win_rate']):>9}{_f(b['edge']):>9}")


def cmd_backtest(args) -> int:
    out = run_backtest(
        args.strategy, assets=_assets(args.assets), windows=_windows(args.windows),
        date_from=parse_any_time(args.date_from), date_to=parse_any_time(args.date_to),
        latency_ms=args.latency, fill_model=args.fill_model, fee_scenario=args.fee_scenario,
        size=args.size, params=json.loads(args.params) if args.params else None,
        compare_random=not args.no_random, persist=not args.no_persist)
    m = out["metrics"]
    print("=" * 70)
    print(f"BACKTEST {args.strategy}  (run_id={out.get('run_id')})")
    print(f"  fill_model={args.fill_model} fee_scenario={args.fee_scenario} latency={args.latency}ms size={args.size}")
    print("=" * 70)
    print(f"  markets={m['n_markets']} acted={m['n_markets_acted']} attempts={m['n_attempts']} "
          f"filled={m['n_filled']} fill_rate={m['fill_rate']}")
    print(f"  win_rate={_pct(m['win_rate'])} avg_entry={m['avg_entry_price']} "
          f"net_pnl={m['net_pnl']} gross_pnl={m['gross_pnl']} fees={m['est_fees']}")
    print(f"  max_dd={m['max_drawdown']} profit_factor={m['profit_factor']} "
          f"vs_random_net={m.get('vs_random_net_pnl')}")
    print(f"  price_fidelity={m['price_fidelity']}  low_sample={m['is_low_sample']}")
    for w in out["warnings"]:
        print(f"  ! {w}")
    return 0


def cmd_replay(args) -> int:
    with session_scope() as db:
        replay = build_replay(db, args.market, fetch_live=not args.no_fetch)
        if replay is None:
            print("market not found", file=sys.stderr)
            return 1
        s = replay["series"]
        print(json.dumps({
            "market": replay["market"], "resolution": replay["resolution"],
            "counts": {"price": len(s["price"]), "book": len(s["book"]),
                       "binance": len(s["binance"]), "chainlink": len(s["chainlink"]),
                       "wallet_trades": len(replay["wallet_trades"])},
        }, indent=2, default=str))
        if args.csv:
            text = market_replay_csv(db, args.market)
            with open(args.csv, "w") as f:
                f.write(text)
            print(f"wrote {args.csv}")
    return 0


def cmd_export(args) -> int:
    with session_scope() as db:
        if args.type == "wallet-trades":
            text = wallet_trades_csv(db, args.wallet or settings.target_wallet)
        elif args.type == "market-replay":
            text = market_replay_csv(db, args.market)
        elif args.type == "strategy-run":
            text = strategy_run_csv(db, int(args.run_id))
        else:
            print(f"unknown export type {args.type}", file=sys.stderr)
            return 1
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"wrote {args.out} ({len(text)} bytes)")
    else:
        sys.stdout.write(text)
    return 0


def cmd_paper_trade(args) -> int:
    from ..paper.engine import PaperConfig, run_paper_session
    latencies = [int(x) for x in args.latencies.split(",") if x.strip()]
    cfg = PaperConfig(
        strategy_key=args.strategy, assets=_assets(args.assets) or settings.assets,
        windows=_windows(args.windows) or settings.windows_minutes,
        latency_grid_ms=latencies, size=args.size, fee_scenario=args.fee_scenario,
        duration_s=args.duration, lookback_s=args.lookback,
        params=json.loads(args.params) if args.params else {},
    )
    print(f"FORWARD PAPER TRADING (SIMULATION — no real orders): strategy={args.strategy} "
          f"assets={cfg.assets} windows={cfg.windows} latencies={latencies}ms "
          f"size={args.size} duration={args.duration or 'until Ctrl-C'}s")
    print("Watching live markets; filling each decision across latency accounts; settling on "
          "real resolutions. Ctrl-C to stop early.\n")
    try:
        result = asyncio.run(run_paper_session(cfg))
    except KeyboardInterrupt:
        print("\nstopped")
        return 0
    print("=" * 78)
    print(f"PAPER SESSION {result['session_id']}  decisions={result['n_decisions']} "
          f"orders={result['n_orders']}")
    print("=" * 78)
    print(f"  {'latency':>8}{'decisions':>11}{'filled':>8}{'settled':>9}{'win_rate':>10}"
          f"{'realized_pnl':>14}{'avg_slip':>10}")
    for s in result["by_latency"]:
        print(f"  {s['latency_ms']:>6}ms{s['n_decisions']:>11}{s['n_filled']:>8}{s['n_settled']:>9}"
              f"{_pct(s['win_rate']):>10}{(s['realized_pnl'] if s['realized_pnl'] is not None else 0):>14.2f}"
              f"{s['avg_slippage_vs_decision']:>10.4f}")
    decay = result.get("pnl_decay_vs_zero_latency")
    if decay:
        print("\n  PnL vs 0ms baseline (the cost of latency):")
        for lat, d in decay.items():
            print(f"    {lat:>5}ms: {d:+.2f}")
    settled = sum(s["n_settled"] for s in result["by_latency"])
    if settled < len(latencies) * 30:
        print("\n  ! LOW SAMPLE: too few settled markets for a statistically meaningful verdict. "
              "Run longer (more windows must resolve).")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("app.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _pct(x):
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "n/a"


def _f(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "  -  "


def configure() -> None:
    configure_logging(settings.log_level, settings.log_json)
