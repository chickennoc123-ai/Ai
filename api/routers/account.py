"""Account endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import AppState, get_account, get_state, require_auth
from broker.xm_account import XMAccount
from utils.exceptions import BrokerError

router = APIRouter(prefix="/api/v1/account", tags=["account"], dependencies=[Depends(require_auth)])


@router.get("", summary="Account information")
async def read_account(account: XMAccount = Depends(get_account)) -> Dict[str, Any]:
    """Return balance, equity, margin and leverage.

    Raises:
        HTTPException: If the broker cannot be reached.
    """
    try:
        return await account.summary()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/equity", summary="Equity only")
async def read_equity(account: XMAccount = Depends(get_account)) -> Dict[str, float]:
    """Return the current equity and balance."""
    info = await account.get_info()
    return {"balance": info.balance, "equity": info.equity, "free_margin": info.free_margin}


@router.get("/history", summary="Persisted account snapshots")
async def read_history(limit: int = 100, state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """Return stored account snapshots, newest first."""
    if state.database is None:
        return {"snapshots": [], "persisted": False}
    from models.account import AccountSnapshot
    from models.database import session_scope

    with session_scope(state.database) as session:
        records = (
            session.query(AccountSnapshot)
            .order_by(AccountSnapshot.created_at.desc())
            .limit(min(limit, 1000))
            .all()
        )
        return {"snapshots": [record.to_dict() for record in records], "persisted": True}
