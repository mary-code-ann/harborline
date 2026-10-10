"""HTTP and WebSocket routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.types import CallerMessage, OpenCall
from app.api.service import (
    AccountNotFound,
    DatabaseUnavailable,
    open_conversation,
    post_message,
    read_trace,
)
from app.db.session import get_session

router = APIRouter()
PAGE = Path(__file__).resolve().parents[1] / "static" / "index.html"


@router.get("/", response_class=HTMLResponse)
async def chat_page() -> str:
    return PAGE.read_text(encoding="utf-8")


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/conversations")
async def start_call(body: OpenCall, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        return await open_conversation(session, body.account_ref.strip())
    except AccountNotFound:
        raise HTTPException(status_code=404, detail="No fictional account uses that reference.")
    except DatabaseUnavailable:
        raise HTTPException(status_code=503, detail="Database is not available.")


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    body: CallerMessage,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        return await post_message(session, conversation_id, body.text.strip())
    except AccountNotFound:
        raise HTTPException(status_code=404, detail="No conversation uses that id.")
    except DatabaseUnavailable:
        raise HTTPException(status_code=503, detail="Database is not available.")


@router.get("/conversations/{conversation_id}/trace")
async def conversation_trace(
    conversation_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        return await read_trace(session, conversation_id)
    except AccountNotFound:
        raise HTTPException(status_code=404, detail="No conversation uses that id.")
    except DatabaseUnavailable:
        raise HTTPException(status_code=503, detail="Database is not available.")


@router.websocket("/ws")
async def chat_socket(websocket: WebSocket, account: str) -> None:
    await websocket.accept()
    try:
        async with websocket.app.state.session_factory() as session:
            opened = await _open_or_explain(websocket, session, account.strip())
            if opened is None:
                return
            await websocket.send_json(opened)
            conversation_id = opened["conversation_id"]
            while True:
                incoming = await websocket.receive_json()
                text = str(incoming.get("text", "")).strip()
                if not text:
                    continue
                await websocket.send_json(await post_message(session, conversation_id, text))
    except WebSocketDisconnect:
        return
    except DatabaseUnavailable:
        await _send_end(websocket, "The database is not available.")


async def _open_or_explain(websocket: WebSocket, session, account: str):
    try:
        return await open_conversation(session, account)
    except AccountNotFound:
        await _send_end(websocket, "No fictional account uses that reference.")
        return None
    except DatabaseUnavailable:
        await _send_end(websocket, "The database is not available.")
        return None


async def _send_end(websocket: WebSocket, text: str) -> None:
    await websocket.send_json({"role": "agent", "text": text, "state": "ENDED"})
    await websocket.close()
