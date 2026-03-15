"""
modules/gateway/feishu.py - Feishu (Lark) WebSocket gateway for STONE (默行者)

Establishes a persistent WebSocket connection to Feishu's event push service.
Handles message events, admin commands, rate limiting, and reconnection with
exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from config import settings
from models.errors import AuthError, PromptInjectionError, StoneError
from models.message import BotResponse, MessageSource, MessageType, UserMessage
from modules.interfaces.gateway import GatewayInterface

if TYPE_CHECKING:
    from core.agent import Agent
    from security.auth import AuthManager
    from security.audit import AuditLogger
    from security.prompt_guard import PromptGuard

logger = logging.getLogger(__name__)

# Rate limiting: max 20 messages per 60 seconds per user
RATE_LIMIT_WINDOW = 60.0
RATE_LIMIT_MAX = 20

# Reconnect parameters
RECONNECT_BASE = 1.0    # seconds
RECONNECT_MAX = 60.0
RECONNECT_MAX_FAILURES = 5

# Long-task threshold: reply immediately if processing takes more than this
LONG_TASK_THRESHOLD = 2.0  # seconds

# Keywords for dry-run confirmation / cancellation
_CONFIRM_WORDS = {"确认", "confirm", "/confirm", "是", "好的", "确定", "执行", "ok", "OK", "好"}
_CANCEL_WORDS = {"取消", "cancel", "/cancel", "否", "不", "算了", "不要", "放弃"}


class FeishuGateway(GatewayInterface):
    """
    Feishu WebSocket long-connection gateway.

    Lifecycle:
        await gateway.start()   # starts WS client + event loop
        await gateway.stop()    # graceful shutdown
    """

    def __init__(
        self,
        agent: "Agent",
        auth: "AuthManager",
        prompt_guard: "PromptGuard",
        audit: "AuditLogger",
    ) -> None:
        self.agent = agent
        self.auth = auth
        self.prompt_guard = prompt_guard
        self.audit = audit

        # Rate limiting: user_id -> deque of timestamps
        self._rate_buckets: dict[str, deque] = defaultdict(deque)
        self._ws_client: Any = None
        self._running = False
        self._reconnect_failures = 0
        self._reconnect_delay = RECONNECT_BASE
        # Serialize WS thread creation to prevent race on lark_oapi.ws.client.loop
        self._ws_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the WebSocket client with reconnection loop."""
        self._running = True
        logger.info("FeishuGateway starting...")

        while self._running:
            try:
                await self._connect_and_run()
                self._reconnect_failures = 0
                self._reconnect_delay = RECONNECT_BASE
            except Exception as exc:
                self._reconnect_failures += 1
                logger.warning(
                    "FeishuGateway connection failed (attempt %d): %s",
                    self._reconnect_failures,
                    exc,
                )
                if self._reconnect_failures >= RECONNECT_MAX_FAILURES:
                    await self.audit.log_security(
                        event_type="reconnect_failure",
                        source_ip="",
                        user_id="system",
                        detail=(
                            f"Feishu WS reconnect failed {self._reconnect_failures} times; "
                            "gateway may be down"
                        ),
                    )
                    logger.error(
                        "FeishuGateway: max reconnect failures reached (%d), "
                        "stopping reconnect loop",
                        RECONNECT_MAX_FAILURES,
                    )
                    self._running = False
                    break

                if not self._running:
                    break

                logger.info(
                    "FeishuGateway: reconnecting in %.0fs...",
                    self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_MAX
                )

    async def stop(self) -> None:
        self._running = False
        if self._ws_client is not None:
            try:
                await self._ws_client.stop()
            except Exception:
                pass
        logger.info("FeishuGateway stopped")

    def is_running(self) -> bool:
        return self._running

    async def send_message(self, user_id: str, content: str) -> None:
        await self.send_reply(receive_id=user_id, content=content)

    # ── Connection ────────────────────────────────────────────────────────────

    async def _connect_and_run(self) -> None:
        """Establish WebSocket connection and start event listening."""
        try:
            import lark_oapi as lark  # type: ignore[import]
        except ImportError as exc:
            raise StoneError(
                message="lark-oapi SDK 未安装，无法启动 Feishu 网关",
                code="IMPORT_ERROR",
            ) from exc

        # Build the HTTP client for sending messages (safe to create here)
        self._lark = lark
        self._client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

        logger.info("FeishuGateway: connecting to Feishu WebSocket...")
        exc_holder: list[Exception] = []
        # Capture uvicorn's event loop so WS thread callbacks can schedule work on it
        main_loop = asyncio.get_event_loop()

        def _run_in_thread() -> None:
            # ws.Client and its asyncio.Lock must be created inside this thread
            # so they bind to new_loop, not uvicorn's loop.
            # Hold _ws_lock for the entire lifetime of this connection to prevent
            # concurrent threads from overwriting lark_oapi.ws.client.loop.
            import lark_oapi as _lark
            import lark_oapi.ws.client as _lark_ws

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            with self._ws_lock:
                _lark_ws.loop = new_loop

                # lark_oapi calls handlers synchronously from the WS thread.
                # Fire-and-forget onto uvicorn's event loop — do NOT block
                # here, otherwise the WS loop can't send pings and Feishu
                # will consider the connection dead during LLM inference.
                def _sync_on_message(data: Any) -> None:
                    asyncio.run_coroutine_threadsafe(
                        self._on_message_receive(data), main_loop
                    )

                event_handler = (
                    _lark.EventDispatcherHandler.builder("", "")
                    .register_p2_im_message_receive_v1(_sync_on_message)
                    .build()
                )
                ws_client = _lark.ws.Client(
                    settings.feishu_app_id,
                    settings.feishu_app_secret,
                    event_handler=event_handler,
                    log_level=_lark.LogLevel.INFO,
                )
                self._ws_client = ws_client
                try:
                    ws_client.start()
                except Exception as e:
                    exc_holder.append(e)
                finally:
                    new_loop.close()

        t = threading.Thread(target=_run_in_thread, daemon=True)
        t.start()
        # Use run_in_executor so the uvicorn event loop is not blocked
        # while the WS thread is running.
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, t.join)
        if exc_holder:
            raise exc_holder[0]

    # ── Event Handler ─────────────────────────────────────────────────────────

    async def _on_message_receive(self, data: Any) -> None:
        """
        Called by lark-oapi for each im.message.receive.v1 event.
        Runs auth, rate limit, prompt guard, then dispatches to agent.
        """
        try:
            event = data.event
            sender = event.sender
            msg = event.message

            open_id: str = sender.sender_id.open_id or ""
            message_id: str = msg.message_id or ""
            chat_id: str = msg.chat_id or ""
            content_raw: str = msg.content or ""

            # Parse JSON content from Feishu format
            import json as _json
            try:
                content_obj = _json.loads(content_raw)
                text_content: str = content_obj.get("text", content_raw)
            except (_json.JSONDecodeError, AttributeError):
                text_content = content_raw

            text_content = text_content.strip()
            logger.info(
                "FeishuGateway: message from open_id=%s: %r",
                open_id[:12] + "***",
                text_content[:80],
            )

            # ── Auth check ────────────────────────────────────────────────
            if not self.auth.verify_user(open_id):
                logger.warning(
                    "FeishuGateway: blocked non-whitelisted user open_id=%s",
                    open_id[:12] + "***",
                )
                await self.audit.log_security(
                    event_type="whitelist_block",
                    source_ip="",
                    user_id=open_id,
                    detail="Non-whitelisted open_id attempted to send message",
                )
                return

            # ── Rate limiting ─────────────────────────────────────────────
            if not self._check_rate_limit(open_id):
                await self.send_reply(chat_id, message_id, "请求过于频繁，请稍后再试。")
                await self.audit.log_security(
                    event_type="rate_limit",
                    source_ip="",
                    user_id=open_id,
                    detail="Rate limit exceeded",
                )
                return

            # ── Admin commands ────────────────────────────────────────────
            if text_content.startswith("/"):
                response = await self._handle_admin_command(
                    text_content, open_id
                )
                if response:
                    await self.send_reply(chat_id, message_id, response)
                return

            # ── Dry-run confirmation / cancellation ───────────────────────
            if self.agent.dry_run_manager.has_pending(chat_id):
                stripped = text_content.strip()
                if stripped in _CONFIRM_WORDS:
                    bot_response = await self.agent.execute_confirmed(chat_id, open_id)
                    await self.send_reply(chat_id, message_id, bot_response.content)
                    return
                if stripped in _CANCEL_WORDS:
                    try:
                        await self.agent.dry_run_manager.cancel(chat_id, open_id)
                    except Exception:
                        pass
                    await self.send_reply(chat_id, message_id, "已取消操作。")
                    return

            # ── Prompt guard ──────────────────────────────────────────────
            try:
                safe_content = self.prompt_guard.wrap_untrusted(
                    text_content, source="feishu"
                )
                self.prompt_guard.scan(safe_content)
            except PromptInjectionError as exc:
                logger.warning(
                    "PromptInjection detected from open_id=%s: %s",
                    open_id[:12] + "***",
                    exc.message,
                )
                await self.send_reply(
                    chat_id,
                    message_id,
                    "检测到疑似提示词注入攻击，已拒绝处理。",
                )
                await self.audit.log_security(
                    event_type="prompt_injection",
                    source_ip="",
                    user_id=open_id,
                    detail=str(exc.pattern),
                )
                return

            # ── Build UserMessage ─────────────────────────────────────────
            user_msg = UserMessage(
                conv_id=chat_id,          # stable per Feishu chat, enables dry-run resumption
                user_id=open_id,
                open_id=open_id,
                message_type=MessageType.TEXT,
                source=MessageSource.FEISHU,
                content=text_content,
                raw_content=content_raw,
            )

            # ── Long-task: send "处理中" immediately ──────────────────────
            start = asyncio.get_event_loop().time()
            ack_task = asyncio.ensure_future(
                self._maybe_send_ack(chat_id, message_id, start)
            )

            try:
                bot_response: BotResponse = await self.agent.process(user_msg)
            finally:
                ack_task.cancel()

            content = bot_response.content
            if bot_response.requires_confirmation:
                content += "\n\n---\n回复「**确认**」执行 / 回复「**取消**」放弃"
            await self.send_reply(chat_id, message_id, content)

        except Exception as exc:
            logger.exception("FeishuGateway: unhandled error in message handler: %s", exc)
            try:
                await self.send_reply(
                    chat_id if "chat_id" in dir() else "",
                    message_id if "message_id" in dir() else "",
                    "系统错误，请稍后重试。",
                )
            except Exception:
                pass

    async def _maybe_send_ack(
        self, chat_id: str, message_id: str, start: float
    ) -> None:
        """Send '收到，处理中...' if the agent takes too long to respond."""
        await asyncio.sleep(LONG_TASK_THRESHOLD)
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed >= LONG_TASK_THRESHOLD:
            await self.send_reply(chat_id, message_id, "收到，处理中，请稍候...")

    # ── Send Reply ────────────────────────────────────────────────────────────

    async def send_reply(
        self, chat_id: str, message_id: str, content: str
    ) -> None:
        """Send a text reply to a Feishu message thread."""
        if not chat_id and not message_id:
            return

        import json as _json

        try:
            import lark_oapi as lark  # type: ignore[import]
            from lark_oapi.api.im.v1 import (  # type: ignore[import]
                CreateMessageRequest,
                CreateMessageRequestBody,
            )

            # Use CreateMessage to chat_id so the reply appears as a new
            # message in the conversation, not as a collapsed thread reply.
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(_json.dumps({"text": content}, ensure_ascii=False))
                .msg_type("text")
                .build()
            )
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )

            loop = asyncio.get_event_loop()
            logger.info(
                "FeishuGateway: sending message to chat_id=%s",
                chat_id[:12] + "***" if chat_id else "(empty)",
            )
            resp = await loop.run_in_executor(
                None, lambda: self._client.im.v1.message.create(req)
            )

            if not resp.success():
                logger.warning(
                    "FeishuGateway: send failed code=%s msg=%s",
                    resp.code,
                    resp.msg,
                )
            else:
                logger.info("FeishuGateway: message sent OK")
        except Exception as exc:
            logger.error("FeishuGateway: send_reply failed: %s", exc)

    # ── Admin Commands ────────────────────────────────────────────────────────

    async def _handle_admin_command(
        self, text: str, open_id: str
    ) -> str | None:
        """Handle /slash admin commands."""
        parts = text.strip().split()
        cmd = parts[0].lower()

        if cmd == "/tasks":
            from registry.skill_registry import SkillRegistry
            # List scheduled tasks for this user
            return "计划任务功能通过 /api/admin/tasks 管理。"

        if cmd == "/skills":
            return "可用技能通过 /api/admin/skills 查看。"

        if cmd in ("/help", "/?"):
            return (
                "**默行者 STONE 命令列表**\n"
                "/tasks  - 查看计划任务\n"
                "/skills - 查看可用技能\n"
                "/help   - 显示此帮助"
            )

        return None

    # ── Rate Limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(self, user_id: str) -> bool:
        """Sliding window rate limiter. Returns True if allowed."""
        now = time.monotonic()
        bucket = self._rate_buckets[user_id]

        # Remove timestamps outside the window
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW:
            bucket.popleft()

        if len(bucket) >= RATE_LIMIT_MAX:
            return False

        bucket.append(now)
        return True


__all__ = ["FeishuGateway"]
