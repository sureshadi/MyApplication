"""Username and password protection for the Portfolio page and the APIs only it uses.

Credentials come from environment variables (PORTFOLIO_USER, PORTFOLIO_PASSWORD), never from the code.
After signing in, the browser keeps a signed, HttpOnly session cookie. If no password is configured,
Portfolio stays locked: nobody can sign in until one is set.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import quote

COOKIE_NAME = "mh_session"

# Paths that need a signed-in session. News tabs, ticker pages and the top ticker bar stay public.
PROTECTED_PAGES = ("/portfolio",)
PROTECTED_API_PREFIXES = ("/api/performance", "/api/research/")


def is_protected(path: str) -> bool:
    if path in PROTECTED_PAGES or path.rstrip("/") in PROTECTED_PAGES:
        return True
    if any(path.startswith(p) for p in PROTECTED_API_PREFIXES):
        return True
    # The Portfolio side panel's company news: /api/ticker/{symbol}/news
    parts = path.strip("/").split("/")
    return len(parts) == 4 and parts[:2] == ["api", "ticker"] and parts[3] == "news"


class Authenticator:
    def __init__(self, user: str | None, password: str | None, secret: str | None, max_age_seconds: int):
        self.user = user or ""
        self.password = password or ""
        self.max_age_seconds = max_age_seconds
        # Without an explicit secret, derive one from the credentials, so changing the password signs everyone out.
        material = secret or f"portfolio-session:{self.user}:{self.password}"
        self._key = hashlib.sha256(material.encode()).digest()

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    def check_credentials(self, user: str, password: str) -> bool:
        if not self.configured:
            return False
        user_ok = hmac.compare_digest(user.strip().lower().encode(), self.user.lower().encode())
        password_ok = hmac.compare_digest(password.encode(), self.password.encode())
        return user_ok and password_ok

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def make_token(self, now: float | None = None) -> str:
        expires = int((now or time.time()) + self.max_age_seconds)
        payload = f"{self.user}|{expires}"
        return f"{payload}|{self._sign(payload)}"

    def valid_token(self, token: str | None, now: float | None = None) -> bool:
        if not token or not self.configured:
            return False
        try:
            user, expires, signature = token.rsplit("|", 2)
            expired = int(expires) < (now or time.time())
        except ValueError:
            return False
        if expired or user != self.user:
            return False
        return hmac.compare_digest(signature, self._sign(f"{user}|{expires}"))


class LoginThrottle:
    """Slows down password guessing: after `limit` failures from one address, wait `window` seconds."""

    def __init__(self, limit: int = 5, window_seconds: int = 900):
        self.limit = limit
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(key, []) if now - t < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, key: str, now: float | None = None) -> bool:
        return len(self._recent(key, now or time.time())) >= self.limit

    def fail(self, key: str, now: float | None = None) -> None:
        now = now or time.time()
        self._failures[key] = self._recent(key, now) + [now]
        if len(self._failures) > 10_000:  # keep memory bounded
            self._failures.clear()

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def safe_next(target: str | None) -> str:
    """Where to go after signing in: only a path on this site, never another host."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/portfolio"
    return target


def login_url(next_path: str) -> str:
    return "/login?next=" + quote(next_path, safe="/")
