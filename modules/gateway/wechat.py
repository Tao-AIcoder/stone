"""
modules/gateway/wechat.py - WeChat gateway stub for STONE (默行者)

TODO: Phase 2 - implement WeChat Work (企业微信) gateway.

Requirements (Phase 2):
- WeChat Work WebHook or event callback URL
- Message verification (token + timestamp + nonce)
- Markdown card message format for rich responses
- Media file handling
- OAuth user authentication

Config keys needed (Phase 2):
- WECHAT_CORP_ID
- WECHAT_AGENT_ID
- WECHAT_SECRET
- WECHAT_TOKEN
- WECHAT_ENCODING_AES_KEY
"""

from __future__ import annotations

from typing import Any


class WechatGateway:
    """
    TODO: Phase 2 - implement WeChat Work gateway.
    """

    async def start(self) -> None:
        raise NotImplementedError("WechatGateway not implemented (Phase 2)")

    async def stop(self) -> None:
        pass

    async def send_reply(self, user_id: str, content: str) -> None:
        raise NotImplementedError("WechatGateway not implemented (Phase 2)")


__all__ = ["WechatGateway"]
