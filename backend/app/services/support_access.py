"""Short-lived support access tokens (phone-bound), in-memory like admin sessions."""

import secrets
import time

_TTL_SEC = 7 * 24 * 3600
_tokens: dict[str, dict[str, float | str]] = {}


def issue_token(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    _tokens[token] = {"phone": phone, "exp": time.time() + _TTL_SEC}
    return token


def phone_from_token(token: str | None) -> str | None:
    if not token:
        return None
    row = _tokens.get(token)
    if not row:
        return None
    if float(row["exp"]) < time.time():
        _tokens.pop(token, None)
        return None
    return str(row["phone"])


def revoke_token(token: str | None) -> None:
    if token:
        _tokens.pop(token, None)
