"""Notification service: log, Telegram and e-mail alerting."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from models.database import Database, session_scope
from models.metrics import SystemEvent
from utils.config import Config, get_config
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)

LEVEL_ICONS = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨", "SUCCESS": "✅"}


class NotificationService:
    """Fans alerts out to the configured channels."""

    def __init__(self, config: Optional[Config] = None, database: Optional[Database] = None) -> None:
        """Initialise the service from configuration."""
        self.config = config or get_config()
        self.database = database
        self.enabled = self.config.get_bool("notifications.enabled", True)
        self.channels: List[str] = [
            str(channel).lower() for channel in self.config.get_list("notifications.channels", ["log"])
        ]
        self.history: List[Dict[str, Any]] = []

    async def notify(
        self,
        message: str,
        level: str = "INFO",
        category: str = "system",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a notification on every configured channel.

        Args:
            message: Human readable text.
            level: ``INFO``, ``WARNING``, ``CRITICAL`` or ``SUCCESS``.
            category: Logical grouping (``risk``, ``trading``, ``research`` ...).
            payload: Structured context stored with the event.

        Returns:
            A record describing the delivery attempt.
        """
        record = {
            "message": message,
            "level": level.upper(),
            "category": category,
            "payload": payload or {},
            "timestamp": utcnow().isoformat(),
            "delivered": [],
        }
        if not self.enabled:
            return record

        for channel in self.channels:
            try:
                if channel == "log":
                    self._log(record)
                elif channel == "telegram":
                    await self._telegram(record)
                elif channel == "email":
                    await asyncio.to_thread(self._email, record)
                else:
                    continue
                record["delivered"].append(channel)
            except Exception as exc:  # noqa: BLE001 - alerting must never crash the caller
                logger.warning("Notification channel failed", channel=channel, error=str(exc))

        self._persist(record)
        self.history.append(record)
        self.history = self.history[-200:]
        return record

    def _log(self, record: Dict[str, Any]) -> None:
        """Emit the notification through the logging pipeline."""
        level = record["level"]
        text = f"{LEVEL_ICONS.get(level, '')} {record['message']}".strip()
        log = logger.error if level == "CRITICAL" else logger.warning if level == "WARNING" else logger.info
        log(text, category=record["category"], **record["payload"])

    async def _telegram(self, record: Dict[str, Any]) -> None:
        """Send the notification to a Telegram chat.

        Raises:
            RuntimeError: If the bot is not configured or the API rejects it.
        """
        token = str(self.config.get("notifications.telegram.bot_token", ""))
        chat_id = str(self.config.get("notifications.telegram.chat_id", ""))
        if not token or not chat_id:
            raise RuntimeError("Telegram bot token or chat id is missing")

        import aiohttp

        text = f"{LEVEL_ICONS.get(record['level'], '')} *{record['level']}* - {record['message']}"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(
                url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Telegram API returned {response.status}")

    def _email(self, record: Dict[str, Any]) -> None:
        """Send the notification by e-mail (blocking, run in a thread).

        Raises:
            RuntimeError: If SMTP is not configured.
        """
        host = str(self.config.get("notifications.email.host", ""))
        recipient = str(self.config.get("notifications.email.to", ""))
        if not host or not recipient:
            raise RuntimeError("SMTP host or recipient is missing")

        message = EmailMessage()
        message["Subject"] = f"[EA Factory Pro] {record['level']} - {record['category']}"
        message["From"] = str(self.config.get("notifications.email.user", "ea-factory@localhost"))
        message["To"] = recipient
        message.set_content(f"{record['message']}\n\n{record['payload']}")

        port = self.config.get_int("notifications.email.port", 587)
        user = str(self.config.get("notifications.email.user", ""))
        password = str(self.config.get("notifications.email.password", ""))
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(message)

    def _persist(self, record: Dict[str, Any]) -> None:
        """Store the notification in the audit log."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                session.add(
                    SystemEvent(
                        level=record["level"],
                        category=record["category"],
                        source="notification_service",
                        message=record["message"],
                        payload=record["payload"],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Unable to persist notification", error=str(exc))

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent notifications, newest first."""
        return list(reversed(self.history))[:limit]
