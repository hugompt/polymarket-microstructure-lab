from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ...config import settings
from ...db.session import get_db
from ...services import export as exporters

router = APIRouter(tags=["export"])


def _csv_response(text: str, filename: str) -> PlainTextResponse:
    return PlainTextResponse(
        content=text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/wallet-trades")
def export_wallet_trades(wallet: str = Query(default=None), db: Session = Depends(get_db)):
    wallet = wallet or settings.target_wallet
    text = exporters.wallet_trades_csv(db, wallet)
    return _csv_response(text, f"wallet-trades-{wallet[:10]}.csv")


@router.get("/export/market-replay")
def export_market_replay(market: str = Query(...), db: Session = Depends(get_db)):
    text = exporters.market_replay_csv(db, market)
    return _csv_response(text, f"market-replay-{market}.csv")


@router.get("/export/strategy-run")
def export_strategy_run(run_id: int = Query(...), db: Session = Depends(get_db)):
    text = exporters.strategy_run_csv(db, run_id)
    if not text.strip():
        raise HTTPException(404, "no trades for run")
    return _csv_response(text, f"strategy-run-{run_id}.csv")
