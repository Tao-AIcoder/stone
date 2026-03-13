"""
modules/interfaces/auth.py - Authentication interface.

Built-in drivers:
  whitelist → security.auth.AuthManager  (Phase 1, default)
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AuthInterface(ABC):
    """
    Contract for user authentication and rate limiting.

    Covers whitelist checks, PIN verification, TOTP, and rate limits.
    """

    @abstractmethod
    def verify_user(self, open_id: str) -> bool:
        """Return True if the user is on the whitelist."""
        ...

    @abstractmethod
    async def verify_pin(self, pin: str, user_id: str = "default_user") -> bool:
        """
        Verify a PIN for the given user.

        Implements strike-based lockout on repeated failures.
        Returns True on success, False on wrong PIN.
        Raises AuthError if account is locked.
        """
        ...

    @abstractmethod
    def verify_totp(self, token: str) -> bool:
        """Verify a TOTP one-time password. Returns True if valid."""
        ...

    @abstractmethod
    def check_rate_limit(self, user_id: str) -> bool:
        """
        Check whether the user is within the rate limit.

        Returns True if allowed, False if rate limit exceeded.
        """
        ...


__all__ = ["AuthInterface"]
