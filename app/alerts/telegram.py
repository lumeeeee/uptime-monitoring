from __future__ import annotations

import httpx

from app.alerts.base import AlertEvent, AlertSender
from app.core.config import settings
from sqlalchemy import select
from app.db.session import get_session
from app.db.models import NotificationChannel


class TelegramNotifier(AlertSender):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=5.0)
        if not settings.telegram_bot_token:
            raise RuntimeError("Telegram bot token is not configured")
        self._token = settings.telegram_bot_token
        # legacy single-chat support (optional)
        self._chat_id = settings.telegram_chat_id
        self._parse_mode = settings.telegram_parse_mode

    async def send(self, event: AlertEvent) -> None:
        text = self._format_message(event)
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"

        async def _post(chat_id: str) -> None:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": self._parse_mode,
                "disable_web_page_preview": True,
            }
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()

        # If explicit chat_id provided in settings, send only there (legacy)
        if self._chat_id:
            await _post(self._chat_id)
            return

        # Otherwise send to all active NotificationChannel entries of type 'telegram'
        async for session in get_session():
            rows = await session.scalars(
                select(NotificationChannel).where(
                    NotificationChannel.type == "telegram",
                    NotificationChannel.is_active.is_(True),
                )
            )
            channels = rows.all()
            for ch in channels:
                chat = ch.config.get("chat_id")
                if chat:
                    try:
                        await _post(str(chat))
                    except Exception:
                        # swallow per-channel errors; caller should log if needed
                        continue

    def _format_message(self, event: AlertEvent) -> str:
        status_line = f"Статус: {event.status.value}"
        prev = f" (предыдущий: {event.previous_status.value})" if event.previous_status else ""
        incident = f"\nИнцидент: {event.incident_id}" if event.incident_id else ""
        err = f"\nОшибка: {event.error}" if event.error else ""
        window = ""
        if event.started_at or event.ended_at:
            start = event.started_at.isoformat() if event.started_at else "?"
            end = event.ended_at.isoformat() if event.ended_at else "?"
            window = f"\nВремя начала и окончания: {start} → {end}"
        checked = f"\nВремя проверки: {event.checked_at.isoformat()}"
        return (
            f"Site: {event.target_name}\n"
            f"URL: {event.url}\n"
            f"{status_line}{prev}{incident}{window}{err}{checked}"
        )
