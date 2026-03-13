"""
tests/test_auth.py - Unit tests for STONE authentication module.
"""

from __future__ import annotations

import sys
import os
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bcrypt
import pyotp

from security.auth import AuthManager, PIN_MAX_ATTEMPTS, PIN_LOCKOUT_SECONDS
from models.errors import AuthError


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_pin_hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=4)).decode()


TEST_PIN = "TestPin123!"
TEST_TOTP_SECRET = pyotp.random_base32()
TEST_OPEN_ID = "open_id_test_user"
TEST_OPEN_ID_2 = "open_id_other_user"
BLOCKED_OPEN_ID = "open_id_blocked"


# ── Whitelist Tests ───────────────────────────────────────────────────────────

class TestWhitelist:
    def test_whitelisted_user_passes(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_whitelist = [TEST_OPEN_ID, TEST_OPEN_ID_2]
            mock_settings.admin_pin = ""
            mock_settings.totp_secret = ""
            auth = AuthManager()
            assert auth.verify_user(TEST_OPEN_ID) is True

    def test_non_whitelisted_user_blocked(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.admin_pin = ""
            mock_settings.totp_secret = ""
            auth = AuthManager()
            assert auth.verify_user(BLOCKED_OPEN_ID) is False

    def test_empty_open_id_blocked(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.admin_pin = ""
            mock_settings.totp_secret = ""
            auth = AuthManager()
            assert auth.verify_user("") is False

    def test_empty_whitelist_blocks_all(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_whitelist = []
            mock_settings.admin_pin = ""
            mock_settings.totp_secret = ""
            auth = AuthManager()
            assert auth.verify_user(TEST_OPEN_ID) is False


# ── PIN Tests ─────────────────────────────────────────────────────────────────

class TestPIN:
    @pytest.mark.asyncio
    async def test_correct_pin_returns_true(self) -> None:
        hashed = make_pin_hash(TEST_PIN)
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_pin = hashed
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.totp_secret = ""
            auth = AuthManager()
            result = await auth.verify_pin(TEST_PIN, user_id="user1")
        assert result is True

    @pytest.mark.asyncio
    async def test_wrong_pin_returns_false(self) -> None:
        hashed = make_pin_hash(TEST_PIN)
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_pin = hashed
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.totp_secret = ""
            auth = AuthManager()
            result = await auth.verify_pin("WrongPin456", user_id="user1")
        assert result is False

    @pytest.mark.asyncio
    async def test_three_failures_cause_lockout(self) -> None:
        hashed = make_pin_hash(TEST_PIN)
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_pin = hashed
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.totp_secret = ""
            auth = AuthManager()

            for _ in range(PIN_MAX_ATTEMPTS):
                await auth.verify_pin("WrongPin", user_id="user1")

            # 4th attempt should raise AuthError (locked out)
            with pytest.raises(AuthError) as exc_info:
                await auth.verify_pin("WrongPin", user_id="user1")

            assert "锁定" in exc_info.value.message or "locked" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_correct_pin_after_failed_clears_counter(self) -> None:
        hashed = make_pin_hash(TEST_PIN)
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_pin = hashed
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.totp_secret = ""
            auth = AuthManager()

            # 2 failures
            await auth.verify_pin("Wrong1", user_id="user2")
            await auth.verify_pin("Wrong2", user_id="user2")

            # Correct PIN should succeed and reset counter
            result = await auth.verify_pin(TEST_PIN, user_id="user2")
            assert result is True

            # Should be able to fail again (counter was reset)
            result2 = await auth.verify_pin("Wrong3", user_id="user2")
            assert result2 is False

    @pytest.mark.asyncio
    async def test_lockout_checked_before_bcrypt(self) -> None:
        """Once locked, AuthError is raised immediately without bcrypt."""
        hashed = make_pin_hash(TEST_PIN)
        with patch("security.auth.settings") as mock_settings:
            mock_settings.admin_pin = hashed
            mock_settings.admin_whitelist = [TEST_OPEN_ID]
            mock_settings.totp_secret = ""
            auth = AuthManager()

            # Manually set lockout
            auth._pin_failures["user3"] = (
                PIN_MAX_ATTEMPTS,
                time.monotonic() + PIN_LOCKOUT_SECONDS,
            )

            with pytest.raises(AuthError):
                await auth.verify_pin(TEST_PIN, user_id="user3")

    def test_is_locked_out_returns_false_when_not_locked(self) -> None:
        auth = AuthManager()
        assert auth.is_locked_out("no_such_user") is False

    def test_is_locked_out_returns_true_when_locked(self) -> None:
        auth = AuthManager()
        auth._pin_failures["locked_user"] = (3, time.monotonic() + 600)
        assert auth.is_locked_out("locked_user") is True

    def test_reset_lockout(self) -> None:
        auth = AuthManager()
        auth._pin_failures["u"] = (3, time.monotonic() + 600)
        auth.reset_pin_lockout("u")
        assert auth.is_locked_out("u") is False


# ── TOTP Tests ────────────────────────────────────────────────────────────────

class TestTOTP:
    def test_valid_totp_returns_true(self) -> None:
        totp = pyotp.TOTP(TEST_TOTP_SECRET)
        valid_token = totp.now()

        with patch("security.auth.settings") as mock_settings:
            mock_settings.totp_secret = TEST_TOTP_SECRET
            mock_settings.admin_pin = ""
            mock_settings.admin_whitelist = []
            auth = AuthManager()
            assert auth.verify_totp(valid_token) is True

    def test_invalid_totp_returns_false(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.totp_secret = TEST_TOTP_SECRET
            mock_settings.admin_pin = ""
            mock_settings.admin_whitelist = []
            auth = AuthManager()
            assert auth.verify_totp("000000") is False

    def test_totp_without_secret_returns_false(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.totp_secret = ""
            mock_settings.admin_pin = ""
            mock_settings.admin_whitelist = []
            auth = AuthManager()
            assert auth.verify_totp("123456") is False

    def test_invalid_totp_format_returns_false(self) -> None:
        with patch("security.auth.settings") as mock_settings:
            mock_settings.totp_secret = TEST_TOTP_SECRET
            mock_settings.admin_pin = ""
            mock_settings.admin_whitelist = []
            auth = AuthManager()
            # Non-numeric token
            assert auth.verify_totp("abcdef") is False


# ── Rate Limiter Tests ────────────────────────────────────────────────────────

class TestRateLimit:
    def test_allows_requests_within_limit(self) -> None:
        auth = AuthManager()
        for _ in range(10):
            assert auth.check_rate_limit("user_rl") is True

    def test_blocks_after_max_requests(self) -> None:
        from security.auth import RATE_LIMIT_MAX
        auth = AuthManager()
        for _ in range(RATE_LIMIT_MAX):
            auth.check_rate_limit("user_overload")
        # Next request should be blocked
        assert auth.check_rate_limit("user_overload") is False

    def test_rate_limit_is_per_user(self) -> None:
        from security.auth import RATE_LIMIT_MAX
        auth = AuthManager()
        # Fill up one user's bucket
        for _ in range(RATE_LIMIT_MAX):
            auth.check_rate_limit("user_a")
        # Other user should still be allowed
        assert auth.check_rate_limit("user_b") is True
