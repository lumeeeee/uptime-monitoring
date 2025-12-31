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

    # Additional commands
    if cmd == "/help":
        help_text = (
            "Доступные команды:\n"
            "/help — показать эту справку\n"
            "/ping — проверить, отвечает ли бот\n"
            "/subscribe или /start — подписаться на уведомления\n"
            "/unsubscribe — отписаться от уведомлений\n"
            "/settings — показать настройки уведомлений\n"
            "Для изменения настроек: /settings parse_mode <Markdown|HTML>"
        )
        if settings.telegram_bot_token:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": chat_id, "text": help_text})
        return Response(status_code=200)

    if cmd == "/ping":
        pong = "Мониторинг доступен"
        if settings.telegram_bot_token:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(url, json={"chat_id": chat_id, "text": pong})
        return Response(status_code=200)

    if cmd == "/settings":
        parts = text.split()
        # find or create channel row for this chat
        rows = await session.scalars(
            select(NotificationChannel).where(NotificationChannel.type == "telegram")
        )
        found = None
        for ch in rows.all():
            if str(ch.config.get("chat_id")) == str(chat_id):
                found = ch
                break

        if len(parts) == 1:
            # show settings
            if found:
                cfg = found.config or {}
                cfg_text = "\n".join(f"{k}: {v}" for k, v in cfg.items()) if cfg else "(по умолчанию)"
                example = (
                    "Примеры использования:\n"
                    "/settings incident_id on — показывать номер инцидента\n"
                    "/settings checked_at off — не показывать время проверки\n"
                    "/settings parse_mode Markdown — форматировать сообщения как Markdown\n"
                )
                msg = f"Ваши настройки:\n{cfg_text}\n\n{example}"
            else:
                msg = "Вы не подписаны. Отправьте /start чтобы подписаться."
            if settings.telegram_bot_token:
                url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
                async with httpx.AsyncClient() as client:
                    await client.post(url, json={"chat_id": chat_id, "text": msg})
            return Response(status_code=200)

        # handle settings change: e.g. /settings parse_mode Markdown
        # handle settings change: parse_mode or toggles for incident_id/checked_at
        if len(parts) >= 3:
            key = parts[1].lower()
            val = parts[2].lower()
            if val not in ("on", "off"):
                # only accept on/off for these settings
                return Response(status_code=200)

            on = val == "on"

            if not found:
                cfg = {"chat_id": str(chat_id), "username": username}
                # set default flags
                cfg.setdefault("include_incident_id", True)
                cfg.setdefault("include_checked_at", True)
                cfg.setdefault("parse_mode", settings.telegram_parse_mode)
                nc = NotificationChannel(type="telegram", config=cfg, is_active=True)
                session.add(nc)
                found = nc

            cfg = found.config or {}
            if key == "parse_mode":
                # allow explicit parse_mode values
                cfg["parse_mode"] = parts[2]
                msg = f"Настройка parse_mode обновлена: {parts[2]}"
            elif key in ("incident_id", "include_incident_id"):
                cfg["include_incident_id"] = on
                msg = f"Показывать номер инцидента: { 'вкл' if on else 'выкл' }"
            elif key in ("checked_at", "include_checked_at"):
                cfg["include_checked_at"] = on
                msg = f"Показывать время проверки: { 'вкл' if on else 'выкл' }"
            else:
                # unknown key
                return Response(status_code=200)

            found.config = cfg
            await session.commit()
            if settings.telegram_bot_token:
                url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
                async with httpx.AsyncClient() as client:
                    await client.post(url, json={"chat_id": chat_id, "text": msg})
            return Response(status_code=200)

    return Response(status_code=200)
