"""
security/auth.py - Authentication and authorization for STONE (默行者)

Handles:
- Feishu open_id whitelist verification
- bcrypt PIN verification with 3-strike lockout
- TOTP verification
- Sliding window rate limiting per user_id
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

import bcrypt
import pyotp

from config import settings
from models.errors import AuthError
from modules.interfaces.auth import AuthInterface

logger = logging.getLogger(__name__)

PIN_MAX_ATTEMPTS = 3
PIN_LOCKOUT_SECONDS = 600   # 10 minutes

RATE_LIMIT_WINDOW = 60.0    # seconds
RATE_LIMIT_MAX = 60         # requests per window (auth checks)


class AuthManager(AuthInterface):
    """
    Manages user authentication for STONE.
    All state is in-memory; meant to be a singleton via ModuleLoader.
    """

    def __init__(self) -> None:
        # PIN lockout: user_id -> (fail_count, lockout_until_monotonic)
        self._pin_failures: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

        # Rate limiting: user_id -> deque of request timestamps
        self._rate_buckets: dict[str, deque] = defaultdict(deque)

    # ── Whitelist ─────────────────────────────────────────────────────────────

    def verify_user(self, open_id: str) -> bool:
        """
        Check if the Feishu open_id is in the admin whitelist.
        Returns True if allowed, False otherwise.
        """
        if not open_id:
            return False
        allowed = settings.admin_whitelist
        result = open_id in allowed
        if not result:
            logger.warning(
                "Auth: rejected open_id %s (not in whitelist)",
                open_id[:12] + "***",
            )
        return result

    # ── PIN ───────────────────────────────────────────────────────────────────

    async def verify_pin(self, pin: str, user_id: str = "default_user") -> bool:
        """
        Verify the admin PIN using bcrypt comparison.

        Raises:
            AuthError: if the account is locked out.
        Returns:
            True on success, False on wrong PIN.
        """
        async with self._lock:
            fail_count, lockout_until = self._pin_failures.get(user_id, (0, 0.0))

            if lockout_until > time.monotonic():
                remaining = int(lockout_until - time.monotonic())
                raise AuthError(
                    f"账户已锁定，请在 {remaining} 秒后重试"
                )

        if not settings.admin_pin:
            logger.warning("Auth: ADMIN_PIN not configured, PIN verification disabled")
            return False

        # bcrypt comparison (blocking - run in executor)
        loop = asyncio.get_event_loop()
        try:
            match = await loop.run_in_executor(
                None,
                lambda: bcrypt.checkpw(
                    pin.encode("utf-8"),
                    settings.admin_pin.encode("utf-8"),
                ),
            )
        except Exception as exc:
            logger.error("Auth: bcrypt error: %s", exc)
            return False

        async with self._lock:
            if match:
                self._pin_failures.pop(user_id, None)
                logger.info("Auth: PIN verified for user %s", user_id)
                return True
            else:
                fail_count += 1
                if fail_count >= PIN_MAX_ATTEMPTS:
                    lockout_until = time.monotonic() + PIN_LOCKOUT_SECONDS
                    self._pin_failures[user_id] = (fail_count, lockout_until)
                    logger.warning(
                        "Auth: PIN lockout triggered for user %s after %d failures",
                        user_id,
                        fail_count,
                    )
                else:
                    self._pin_failures[user_id] = (fail_count, 0.0)
                    logger.warning(
                        "Auth: PIN failure %d/%d for user %s",
                        fail_count,
                        PIN_MAX_ATTEMPTS,
                        user_id,
                    )
                return False

    def is_locked_out(self, user_id: str) -> bool:
        """Return True if the user is currently PIN-locked."""
        _, lockout_until = self._pin_failures.get(user_id, (0, 0.0))
        return lockout_until > time.monotonic()

    def reset_pin_lockout(self, user_id: str) -> None:
        """Manually clear a PIN lockout (admin recovery)."""
        self._pin_failures.pop(user_id, None)

    # ── TOTP ──────────────────────────────────────────────────────────────────

    def verify_totp(self, token: str) -> bool:
        """
        Verify a 6-digit TOTP token using pyotp.
        Uses a 30-second window with ±1 step tolerance.

        Returns True if valid, False otherwise.
        """
        if not settings.totp_secret:
            logger.warning("Auth: TOTP_SECRET not configured, TOTP verification disabled")
            return False

        try:
            totp = pyotp.TOTP(settings.totp_secret)
            valid = totp.verify(token, valid_window=1)
            if not valid:
                logger.warning("Auth: TOTP verification failed")
            return valid
        except Exception as exc:
            logger.error("Auth: TOTP error: %s", exc)
            return False

    # ── Rate Limiting ─────────────────────────────────────────────────────────

    def check_rate_limit(self, user_id: str) -> bool:
        """
        Sliding window rate limiter.
        Returns True if the request is allowed, False if rate-limited.
        """
        now = time.monotonic()
        bucket = self._rate_buckets[user_id]

        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_MAX:
            logger.warning("Auth: rate limit exceeded for user %s", user_id)
            return False

        bucket.append(now)
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def hash_pin(plain_pin: str) -> str:
        """Hash a plain-text PIN for storage. Use this to generate ADMIN_PIN."""
        hashed = bcrypt.hashpw(plain_pin.encode("utf-8"), bcrypt.gensalt(rounds=12))
        return hashed.decode("utf-8")

    @staticmethod
    def generate_totp_secret() -> str:
        """Generate a new BASE32 TOTP secret."""
        return pyotp.random_base32()


__all__ = ["AuthManager"]
