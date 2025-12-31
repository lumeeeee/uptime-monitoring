from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from app.api.dependencies import get_db_session
from app.core.config import settings
from app.db.models import NotificationChannel

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, session: AsyncSession = Depends(get_db_session)) -> Response:
    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return Response(status_code=200)

    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    username = (message.get("from") or {}).get("username")

    if not text or not chat_id:
        return Response(status_code=200)

    cmd = text.split()[0].lower()

    if cmd in ("/start", "/subscribe"):
        # ensure channel exists
        rows = await session.scalars(
            select(NotificationChannel).where(NotificationChannel.type == "telegram")
        )
        found = None
        for ch in rows.all():
            if str(ch.config.get("chat_id")) == str(chat_id):
                found = ch
                break

        if found:
            if not found.is_active:
                found.is_active = True
            msg = "🔔 Вы подписаны на уведомления."
        else:
            nc = NotificationChannel(type="telegram", config={"chat_id": str(chat_id), "username": username}, is_active=True)
            session.add(nc)
            msg = "Подписка оформлена."

        await session.commit()
        # reply to user
        if settings.telegram_bot_token:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": chat_id, "text": msg})

    elif cmd == "/unsubscribe":
        rows = await session.scalars(
            select(NotificationChannel).where(NotificationChannel.type == "telegram")
        )
        removed = False
        for ch in rows.all():
            if str(ch.config.get("chat_id")) == str(chat_id):
                ch.is_active = False
                removed = True
        if removed:
            await session.commit()
            msg = "🔕Вы отписаны от уведомлений."
        else:
            msg = "Вы не были подписаны."

        if settings.telegram_bot_token:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": chat_id, "text": msg})

    return Response(status_code=200)
