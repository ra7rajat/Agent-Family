"""
agent_family.auth.session_store
=================================

Server-side encrypted session store for web OAuth2 sessions.

Design
------
- Sessions are keyed by a cryptographically random session_id (32 bytes hex).
- Token data is Fernet-encrypted at rest in an in-memory dict.
- Sessions auto-expire after SESSION_TTL_DAYS (default: 7).
- Tokens are NEVER logged in plaintext — all log lines mask sensitive values.
- Thread-safe via a single RLock.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet
import json

logger = logging.getLogger(__name__)

MIN_SESSION_TTL_SECONDS = 3600  # Keep sessions for at least 1 hour


def _resolve_session_ttl_seconds() -> int:
    """
    Resolve session TTL from environment with a 1-hour minimum.

    Priority:
    1) SESSION_TTL_SECONDS
    2) SESSION_TTL_DAYS (converted to seconds)
    3) Default 7 days
    """
    ttl_seconds_env = os.getenv("SESSION_TTL_SECONDS")
    if ttl_seconds_env:
        try:
            return max(int(ttl_seconds_env), MIN_SESSION_TTL_SECONDS)
        except ValueError:
            logger.warning(
                "Invalid SESSION_TTL_SECONDS=%r, falling back to SESSION_TTL_DAYS/default",
                ttl_seconds_env,
            )

    ttl_days_env = os.getenv("SESSION_TTL_DAYS", "7")
    try:
        ttl_seconds = int(ttl_days_env) * 86400
    except ValueError:
        logger.warning("Invalid SESSION_TTL_DAYS=%r, using default 7 days", ttl_days_env)
        ttl_seconds = 7 * 86400

    return max(ttl_seconds, MIN_SESSION_TTL_SECONDS)


SESSION_TTL_SECONDS = _resolve_session_ttl_seconds()


def _mask(token: str | None) -> str:
    """Mask a token for safe logging."""
    if not token:
        return "(none)"
    return token[:6] + "****" + token[-4:]


@dataclass
class Session:
    session_id: str
    access_token: str
    refresh_token: str | None
    email: str | None
    name: str | None
    picture: str | None
    expires_at: float  # unix timestamp when session itself expires
    token_expiry: float | None  # unix timestamp when access_token expires

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def token_needs_refresh(self) -> bool:
        if self.token_expiry is None:
            return False
        return time.time() > (self.token_expiry - 60)  # 60s buffer

    def to_public_dict(self) -> dict[str, Any]:
        """Return safe public info (no tokens)."""
        return {
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
        }


class SessionStore:
    """Thread-safe singleton for encrypted in-memory session management."""

    _instance: SessionStore | None = None
    _lock = threading.Lock()

    def __new__(cls) -> SessionStore:
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._init_once()
                cls._instance = inst
            return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Test-only."""
        with cls._lock:
            cls._instance = None

    def _init_once(self) -> None:
        self._rlock = threading.RLock()
        # {session_id: encrypted_bytes}
        self._store: dict[str, bytes] = {}

        key_b64 = os.getenv("TOKEN_ENCRYPTION_KEY")
        if not key_b64:
            raise ValueError("TOKEN_ENCRYPTION_KEY environment variable is required")
        self._fernet = Fernet(key_b64.encode())

    # ── Public API ──────────────────────────────────────────────────────────

    def create_session(
        self,
        access_token: str,
        refresh_token: str | None,
        email: str | None,
        name: str | None,
        picture: str | None,
        token_expiry: float | None = None,
    ) -> str:
        """Encrypt and store a new session. Returns the session_id."""
        session_id = secrets.token_hex(32)
        session = Session(
            session_id=session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            email=email,
            name=name,
            picture=picture,
            expires_at=time.time() + SESSION_TTL_SECONDS,
            token_expiry=token_expiry,
        )
        self._persist(session)
        logger.info(
            "Session created: id=%s email=%s access_token=%s",
            session_id[:8] + "****",
            email,
            _mask(access_token),
        )
        return session_id

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve and decrypt a session. Returns None if missing or expired."""
        with self._rlock:
            encrypted = self._store.get(session_id)
            if not encrypted:
                return None

            try:
                data = json.loads(self._fernet.decrypt(encrypted))
                session = Session(**data)
            except Exception as exc:
                logger.warning("Failed to decrypt session %s: %s", session_id[:8], exc)
                return None

            if session.is_expired():
                logger.info("Session %s expired, removing.", session_id[:8] + "****")
                del self._store[session_id]
                return None

            # Sliding expiration: extend active sessions on each valid read.
            next_expiry = time.time() + SESSION_TTL_SECONDS
            if next_expiry > session.expires_at:
                session.expires_at = next_expiry
                self._persist(session)

            return session

    def update_tokens(
        self,
        session_id: str,
        access_token: str,
        token_expiry: float | None = None,
    ) -> bool:
        """Replace access_token in a session after a refresh."""
        with self._rlock:
            session = self.get_session(session_id)
            if not session:
                return False
            session.access_token = access_token
            session.token_expiry = token_expiry
            self._persist(session)
            logger.info(
                "Token refreshed for session %s: new_token=%s",
                session_id[:8] + "****",
                _mask(access_token),
            )
            return True

    def delete_session(self, session_id: str) -> bool:
        """Remove a session (logout / revoke)."""
        with self._rlock:
            existed = self._store.pop(session_id, None) is not None
            if existed:
                logger.info("Session %s deleted.", session_id[:8] + "****")
            return existed

    def _persist(self, session: Session) -> None:
        """Encrypt and store the session."""
        data = json.dumps(session.__dict__)
        self._store[session.session_id] = self._fernet.encrypt(data.encode())
