"""Administrator sign-in: one account from the environment and a signed, expiring session cookie."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable

COOKIE_NAME = "aicafe_admin"
MIN_PASSWORD_CHARS = 12
MIN_KEY_CHARS = 24


class AdminAuth:
    """Stateless sessions: the cookie holds its expiry and an HMAC of it, so nothing is stored."""

    def __init__(
        self,
        user: str,
        password: str,
        session_key: str,
        session_hours: float = 8.0,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._user = user
        self._password = password
        self._key = session_key.encode("utf-8")
        self._ttl_s = int(session_hours * 3600)
        self._now = now

    @property
    def enabled(self) -> bool:
        """Weak or missing settings keep the whole admin API switched off."""
        return (
            bool(self._user)
            and len(self._password) >= MIN_PASSWORD_CHARS
            and len(self._key) >= MIN_KEY_CHARS
        )

    @property
    def session_seconds(self) -> int:
        return self._ttl_s

    def credentials_ok(self, user: str, password: str) -> bool:
        # Both comparisons always run, so the time taken does not reveal which one was wrong.
        user_ok = hmac.compare_digest(user.encode("utf-8"), self._user.encode("utf-8"))
        password_ok = hmac.compare_digest(password.encode("utf-8"), self._password.encode("utf-8"))
        return self.enabled and user_ok and password_ok

    def issue_token(self) -> str:
        expires = int(self._now()) + self._ttl_s
        return f"{expires}.{self._sign(expires)}"

    def user_for(self, token: str | None) -> str | None:
        """The signed-in user when the token is genuine and not expired, else None."""
        if not self.enabled or not token:
            return None
        expires_text, _, signature = token.partition(".")
        if not expires_text.isdigit() or not hmac.compare_digest(
            signature, self._sign(int(expires_text))
        ):
            return None
        return self._user if int(expires_text) > self._now() else None

    def _sign(self, expires: int) -> str:
        message = f"admin|{self._user}|{expires}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()
