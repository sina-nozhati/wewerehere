import secrets
import time
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_ADMIN_SESSION_TTL_SEC = 7 * 24 * 3600
_sessions: dict[str, float] = {}
_bearer = HTTPBearer(auto_error=False)


def verify_admin_password(password: str) -> bool:
    expected = settings.admin_password
    if not expected:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), expected.encode("utf-8"))
    except ValueError:
        return password == expected


def hash_admin_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_session() -> str:
    token = secrets.token_hex(24)
    _sessions[token] = time.time() + _ADMIN_SESSION_TTL_SEC
    return token


def revoke_session(token: str) -> None:
    _sessions.pop(token, None)


def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp or exp < time.time():
        _sessions.pop(token, None)
        return False
    return True


def require_admin_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    token_query: str | None = Query(None, alias="token"),
) -> str:
    """Accept token from either Authorization header or ?token= query param (for EventSource)."""
    token = None
    if creds:
        token = creds.credentials
    elif token_query:
        token = token_query
    if not is_valid_session(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return token


def require_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    token = creds.credentials if creds else None
    if not is_valid_session(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return token


def check_rate_limit(store: dict[str, list[float]], key: str, limit: int, window_sec: float) -> None:
    import time

    now = time.time()
    hits = store.setdefault(key, [])
    hits[:] = [t for t in hits if now - t < window_sec]
    if len(hits) >= limit:
        raise HTTPException(status_code=429, detail="too many requests")
    hits.append(now)
