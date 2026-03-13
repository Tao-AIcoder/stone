"""
modules/interfaces/gateway.py - Gateway (messaging platform) interface.

Built-in drivers:
  feishu   → modules.gateway.feishu.FeishuGateway   (Phase 1, default)
  telegram → modules.gateway.telegram.TelegramGateway (Phase 2)
  wechat   → modules.gateway.wechat.WeChatGateway    (Phase 2)

To add a new gateway (e.g. Discord):
  1. Create modules/gateway/discord.py implementing GatewayInterface.
  2. Add "discord": "modules.gateway.discord:DiscordGateway" to registry.py.
  3. Set stone.config.json  modules.gateway.driver = "discord".
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class GatewayInterface(ABC):
    """
    Contract for all messaging-platform gateways.

    Lifecycle:
        start()   → background loop, receives messages and calls agent
        stop()    → graceful teardown
        send()    → push a reply to a specific user
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def start(self) -> None:
        """Start the gateway (connect, subscribe, begin receiving messages)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the gateway and release connections."""
        ...

    # ── Messaging ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def send_message(self, user_id: str, content: str) -> None:
        """
        Send a text message to the specified user.

        Args:
            user_id: Platform-specific user identifier (e.g. Feishu open_id).
            content: Plain-text or markdown message content.
        """
        ...

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the gateway is currently connected and receiving."""
        ...


__all__ = ["GatewayInterface"]
