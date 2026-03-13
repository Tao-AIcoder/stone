"""
tests/test_module_auth.py - Unit tests for security/auth.py (AuthManager).

Tests:
- verify_user (whitelist check)
- verify_pin (bcrypt, lockout, unlock)
- verify_totp
- check_rate_limit (sliding window)
- AuthInterface compliance
"""

from __future__ import annotations

import sys
import os
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from security.auth import AuthManager
from models.errors import AuthError
from modules.interfaces.auth import AuthInterface


# ── Fixtures ──────────────────────────────────────────────────────────────────

ADMIN_ID = "open_id_admin"
NOBODY_ID = "open_id_nobody"
VALID_PIN = "supersecret"


@pytest.fixture
def auth(monkeypatch) -> AuthManager:
    """AuthManager with controlled settings."""
    import bcrypt as _bcrypt
    import security.auth as _auth_mod

    hashed_pin = _bcrypt.hashpw(VALID_PIN.encode(), _bcrypt.gensalt()).decode()
    monkeypatch.setattr(_auth_mod.settings, "admin_whitelist", [ADMIN_ID])
    monkeypatch.setattr(_auth_mod.settings, "admin_pin", hashed_pin)
    monkeypatch.setattr(_auth_mod.settings, "totp_secret", "JBSWY3DPEHPK3PXP")
    return AuthManager()


# ── Interface compliance ───────────────────────────────────────────────────────

class TestInterface:
    def test_inherits_auth_interface(self) -> None:
        assert issubclass(AuthManager, AuthInterface)

    def test_has_required_methods(self) -> None:
        mgr = AuthManager.__new__(AuthManager)
        for m in ("verify_user", "verify_pin", "verify_totp", "check_rate_limit"):
            assert hasattr(mgr, m)


# ── verify_user ───────────────────────────────────────────────────────────────

class TestVerifyUser:
    def test_whitelisted_user_returns_true(self, auth: AuthManager) -> None:
        assert auth.verify_user(ADMIN_ID) is True

    def test_unknown_user_returns_false(self, auth: AuthManager) -> None:
        assert auth.verify_user(NOBODY_ID) is False

    def test_empty_string_returns_false(self, auth: AuthManager) -> None:
        assert auth.verify_user("") is False


# ── verify_pin ────────────────────────────────────────────────────────────────

class TestVerifyPin:
    @pytest.mark.asyncio
    async def test_correct_pin_returns_true(self, auth: AuthManager) -> None:
        result = await auth.verify_pin(VALID_PIN, ADMIN_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_wrong_pin_returns_false(self, auth: AuthManager) -> None:
        result = await auth.verify_pin("wrongpin", ADMIN_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_three_failures_triggers_lockout(self, auth: AuthManager) -> None:
        for _ in range(3):
            await auth.verify_pin("wrong", ADMIN_ID)
        with pytest.raises(AuthError):
            await auth.verify_pin("wrong", ADMIN_ID)

    @pytest.mark.asyncio
    async def test_correct_pin_resets_fail_count(self, auth: AuthManager) -> None:
        await auth.verify_pin("wrong", ADMIN_ID)
        await auth.verify_pin("wrong", ADMIN_ID)
        await auth.verify_pin(VALID_PIN, ADMIN_ID)  # reset
        # Should be able to try again without lockout
        result = await auth.verify_pin(VALID_PIN, ADMIN_ID)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_pin_returns_false(self, auth: AuthManager) -> None:
        result = await auth.verify_pin("", ADMIN_ID)
        assert result is False


# ── verify_totp ───────────────────────────────────────────────────────────────

class TestVerifyTotp:
    def test_valid_totp_returns_true(self, auth: AuthManager) -> None:
        import pyotp
        totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
        token = totp.now()
        assert auth.verify_totp(token) is True

    def test_invalid_totp_returns_false(self, auth: AuthManager) -> None:
        assert auth.verify_totp("000000") is False

    def test_empty_token_returns_false(self, auth: AuthManager) -> None:
        assert auth.verify_totp("") is False


# ── check_rate_limit ──────────────────────────────────────────────────────────

class TestRateLimit:
    def test_first_request_is_allowed(self, auth: AuthManager) -> None:
        result = auth.check_rate_limit("user1")
        assert result is True

    def test_within_limit_is_allowed(self, auth: AuthManager) -> None:
        for _ in range(10):
            auth.check_rate_limit("user_a")
        result = auth.check_rate_limit("user_a")
        assert result is True

    def test_exceeding_limit_returns_false(self, auth: AuthManager) -> None:
        # Exhaust the 60-request window
        for _ in range(60):
            auth.check_rate_limit("heavy_user")
        result = auth.check_rate_limit("heavy_user")
        assert result is False

    def test_different_users_have_separate_buckets(self, auth: AuthManager) -> None:
        for _ in range(60):
            auth.check_rate_limit("user_x")
        # user_y should not be affected
        result = auth.check_rate_limit("user_y")
        assert result is True
