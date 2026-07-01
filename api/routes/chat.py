"""
FinOS — agent SSE route (api/routes/agent.py)

POST /agent/chat — streams agent response token by token via SSE

Flow:
    1. Authenticate user via Bearer token
    2. Get or create an in-memory Session for this user
    3. On first message, inject the system prompt
    4. Run agent.core.run() in asyncio.to_thread() (sync → async bridge)
    5. Stream the response word-by-word as SSE events
    6. Terminate stream with data: [DONE]

Session persistence:
    Sessions held in a module-level dict keyed by user_id.
    Intentional for v1 — single user, single process.
    Each session holds conversation history and DependencyState across requests.
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user, get_db
# from agent import llm as agent_llm
from agent.orchestrator import run as orchestrator_run
from agent.session import Session
from core.models import User

router = APIRouter(prefix="/agent", tags=["agent"])

# In-memory session store — keyed by user_id
# Intentionally module-level for v1: single user, single process
_sessions: dict[int, Session] = {}


class ChatRequest(BaseModel):
    message: str


def _get_or_create_session(user: User, db) -> Session:
    """Return existing Session for this user, or create and initialise a new one."""
    if user.id not in _sessions:
        session = Session(
            user_id=user.id,
            username=user.username,
            db_session=db,
        )
        session.add_system_prompt()
        _sessions[user.id] = session
    else:
        # Rebind db_session on every request — SQLModel sessions must not be
        # reused across HTTP requests; tools always get a live session this way
        _sessions[user.id].db_session = db

    return _sessions[user.id]


# async def _stream_response(response: str):
#     """Yield SSE events word-by-word from a complete response string."""
#     words = response.split(" ")
#     for i, word in enumerate(words):
#         chunk = word if i == 0 else " " + word
#         yield f"data: {chunk}\n\n"
#         await asyncio.sleep(0)      # yield control to event loop between tokens
#     yield "data: [DONE]\n\n"


# async def _stream_response(response: str):
#     """Yield the full response as a single SSE event."""
#     yield f"data: {response}\n\n"
#     yield "data: [DONE]\n\n"




# async def _stream_response(response: str):
#     """Yield SSE events word-by-word from a complete response string."""
#     words = response.split(" ")
#     for i, word in enumerate(words):
#         chunk = word if i == 0 else f"\u0020{word}"  # unicode space avoids SSE stripping
#         yield f"data: {chunk}\n\n"
#         await asyncio.sleep(0.02)
#     yield "data: [DONE]\n\n"


async def _stream_response(response: str):
    words = response.split(" ")
    for i, word in enumerate(words):
        chunk = word if i == 0 else " " + word
        yield f"data: {chunk}\n\n"
        await asyncio.sleep(0.02)
    yield "data: [DONE]\n\n"





@router.post("/chat")
async def agent_chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Stream agent response for a user message via SSE."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session = _get_or_create_session(current_user, db)

    async def event_stream():
        try:
            response = await asyncio.to_thread(
                orchestrator_run, body.message, session
            )
            async for event in _stream_response(response):
                yield event
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )