"""
agent_family.server
=====================

FastAPI application with:
  - Web OAuth2 flow  (/auth/login, /auth/callback, /auth/me, /auth/logout)
  - Session-aware SSE chat endpoint  (POST /api/v1/chat)

Session lifecycle
-----------------
1. Browser visits /auth/login → redirect to Google consent page.
2. Google redirects to /auth/callback?code=... → exchange code for tokens,
   create encrypted server-side session, set HTTP-only session cookie.
3. Subsequent requests include the cookie; the server looks up the session,
   extracts the live access_token, and injects it into the MasterAgent run().
4. If Google returns 401, the server auto-refreshes using the refresh_token
   (stored encrypted in the session) without interrupting the user.

Security
--------
- Tokens live only in the in-memory encrypted SessionStore → never in JS.
- HTTP-only + SameSite=Lax cookie prevents XSS and most CSRF attacks.
- All log lines containing tokens are masked (first 6 + last 4 chars only).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from typing import AsyncGenerator

from dotenv import load_dotenv
load_dotenv()

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from agent_family.auth.oauth2 import WebOAuth2Flow
from agent_family.auth.session_store import SESSION_TTL_SECONDS, SessionStore
from agent_family.agents.calendar_agent import calendar_agent, CALENDAR_AGENT_CARD
from agent_family.agents.master_agent import MasterAgent
from agent_family.agents.task_agent import task_agent, TASK_AGENT_CARD
from agent_family.registry.registry import AgentRegistry

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Family API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,  # Required for cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared singletons
_registry = AgentRegistry()
_registry.clear()
_registry.register(CALENDAR_AGENT_CARD)
_registry.register(TASK_AGENT_CARD)

_session_store = SessionStore()
_conversation_state: dict[str, dict[str, str]] = {}

COOKIE_NAME = "agent_session_id"
COOKIE_MAX_AGE = SESSION_TTL_SECONDS

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _get_session_id(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def _require_session(request: Request):
    """Return the Session or raise 401."""
    session_id = _get_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = _session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return session


def _maybe_refresh(session_id: str, session) -> str:
    """
    Proactively refresh access_token if it's close to expiry.
    Returns the (potentially updated) access_token.
    """
    if session.token_needs_refresh() and session.refresh_token:
        try:
            new_tokens = WebOAuth2Flow.refresh_token(session.refresh_token)
            _session_store.update_tokens(
                session_id,
                new_tokens["access_token"],
                new_tokens.get("expiry_timestamp"),
            )
            logger.info("Auto-refreshed token for session %s****", session_id[:8])
            return new_tokens["access_token"]
        except Exception as exc:
            logger.warning("Token refresh failed for session %s****: %s", session_id[:8], exc)
    return session.access_token


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/auth/login", summary="Start Google OAuth2 flow")
async def auth_login():
    """Redirect the browser to Google's consent page."""
    state = secrets.token_urlsafe(32)
    # In production store state in a short-lived cookie for CSRF validation
    auth_url = WebOAuth2Flow.get_authorization_url(state)
    return RedirectResponse(auth_url)


@app.get("/auth/callback", summary="Google OAuth2 callback")
async def auth_callback(code: str, state: str, response: Response):
    """Exchange authorization code for tokens, create session, set cookie."""
    try:
        tokens = WebOAuth2Flow.exchange_code(code)
    except Exception as exc:
        logger.error("OAuth2 code exchange failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"OAuth2 error: {exc}")

    # Decode user info from id_token (JWT — safe to decode without verify here,
    # we just received it directly from Google over TLS)
    import base64
    email = name = picture = None
    try:
        id_token = tokens.get("id_token", "")
        if id_token:
            payload_b64 = id_token.split(".")[1]
            # Fix padding
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            email = payload.get("email")
            name = payload.get("name")
            picture = payload.get("picture")
    except Exception:
        pass  # Non-fatal — we can proceed without display info

    session_id = _session_store.create_session(
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        email=email,
        name=name,
        picture=picture,
        token_expiry=tokens.get("expiry_timestamp"),
    )

    logger.info("New session created for %s (session=%s****)", email, session_id[:8])

    redirect_to = os.getenv("FRONTEND_URL", "http://localhost:3000")
    resp = RedirectResponse(url=redirect_to)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        secure=False,  # Set True in production (HTTPS)
    )
    return resp


@app.get("/auth/me", summary="Get current user info")
async def auth_me(request: Request):
    """Return public user info from the active session, or 401."""
    session = _require_session(request)
    return JSONResponse(session.to_public_dict())


@app.post("/auth/logout", summary="Sign out and clear session")
async def auth_logout(request: Request, response: Response):
    """Delete the server-side session and clear the cookie."""
    session_id = _get_session_id(request)
    if session_id:
        _session_store.delete_session(session_id)
    response.delete_cookie(COOKIE_NAME)
    return {"status": "logged_out"}


# ---------------------------------------------------------------------------
# Chat SSE endpoint
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    prompt: str


async def _generate_sse(
    prompt: str,
    access_token: str | None,
    refresh_token: str | None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run MasterAgent and yield SSE events."""
    master = MasterAgent(registry=_registry)
    event_queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        master.run(
            prompt,
            event_queue=event_queue,
            access_token=access_token,
            refresh_token=refresh_token,
            context=_conversation_state.get(session_id or "", {}),
        )
    )

    try:
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
                continue
            except asyncio.TimeoutError:
                # If the worker task finished but never emitted a terminal event,
                # terminate the stream explicitly so the frontend does not hang.
                if task.done():
                    exc = task.exception()
                    if exc is not None:
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "type": "completed",
                                    "agent": "MasterAgent",
                                    "message": f"Error: {exc}",
                                }
                            )
                            + "\n\n"
                        )
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "done",
                                "agent": "MasterAgent",
                                "message": "Stream finished",
                            }
                        )
                        + "\n\n"
                    )
                    break
    except asyncio.CancelledError:
        task.cancel()
    finally:
        if not task.done():
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if session_id and task.done() and not task.cancelled():
            try:
                result = task.result()
                if result.results:
                    state = {
                        "last_agent_name": result.results[-1].agent_name,
                        "last_skill_id": result.results[-1].skill_id,
                    }
                    for res in reversed(result.results):
                        if res.agent_name == "TaskAgent" and res.skill_id == "list_tasks" and res.output:
                            titles: list[str] = []
                            for line in res.output.splitlines():
                                line = line.strip()
                                if line.startswith("- "):
                                    titles.append(line[2:].strip())
                            if titles:
                                state["last_task_titles"] = "|||".join(titles)
                            break
                    _conversation_state[session_id] = state
            except Exception:
                pass


@app.post("/api/v1/chat", summary="Stream multi-agent responses via SSE")
async def chat_endpoint(req: ChatRequest, request: Request):
    """
    Session-aware SSE chat endpoint.
    Requires a valid session cookie.
    Extracts the user's access_token (auto-refreshing if needed) and passes
    it to the MasterAgent so sub-agents can call Google APIs on behalf of the user.
    """
    # Soft auth: if no session, return 401 JSON (frontend will show sign-in prompt)
    session_id = _get_session_id(request)
    access_token = None
    refresh_token = None

    if session_id:
        session = _session_store.get_session(session_id)
        if session:
            access_token = _maybe_refresh(session_id, session)
            refresh_token = session.refresh_token
        else:
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired. Please sign in again."},
            )
    else:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated. Please sign in."},
        )

    return StreamingResponse(
        _generate_sse(req.prompt, access_token, refresh_token, session_id=session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
