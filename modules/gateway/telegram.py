"""
modules/gateway/telegram.py - Telegram gateway stub for STONE (默行者)

TODO: Phase 2 - implement Telegram Bot API gateway.

Requirements (Phase 2):
- python-telegram-bot >= 20.0 (add to requirements.txt)
- TELEGRAM_BOT_TOKEN env var
- Long-polling or webhook mode
- Inline keyboard for dry-run confirm/cancel
- File upload/download support
- User ID -> STONE user_id mapping
- Whitelist enforcement via Telegram user_id
"""

from __future__ import annotations


class TelegramGateway:
    """
    TODO: Phase 2 - implement Telegram Bot gateway.
    """

    async def start(self) -> None:
        raise NotImplementedError("TelegramGateway not implemented (Phase 2)")

    async def stop(self) -> None:
        pass

    async def send_reply(self, chat_id: int, content: str) -> None:
        raise NotImplementedError("TelegramGateway not implemented (Phase 2)")


__all__ = ["TelegramGateway"]
