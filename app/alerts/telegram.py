from __future__ import annotations

import httpx

from app.alerts.base import AlertEvent, AlertSender
from app.core.config import settings


class TelegramNotifier(AlertSender):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=5.0)
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise RuntimeError("Telegram credentials are not configured")
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._parse_mode = settings.telegram_parse_mode

    async def send(self, event: AlertEvent) -> None:
        text = self._format_message(event)
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": True,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()

    def _format_message(self, event: AlertEvent) -> str:
        status_line = f"Status: {event.status.value}"
        prev = f" (prev: {event.previous_status.value})" if event.previous_status else ""
        incident = f"\nIncident: {event.incident_id}" if event.incident_id else ""
        err = f"\nError: {event.error}" if event.error else ""
        window = ""
        if event.started_at or event.ended_at:
            start = event.started_at.isoformat() if event.started_at else "?"
            end = event.ended_at.isoformat() if event.ended_at else "?"
            window = f"\nWindow: {start} → {end}"
        checked = f"\nChecked at: {event.checked_at.isoformat()}"
        return (
            f"Site: {event.target_name}\n"
            f"URL: {event.url}\n"
            f"{status_line}{prev}{incident}{window}{err}{checked}"
        )
