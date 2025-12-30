from __future__ import annotations

import hmac
import hashlib
from datetime import timedelta, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.core.config import settings
from app.services.sites import SiteService

router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)

COOKIE_NAME = "uptime_admin"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


def _sign(val: str) -> str:
    digest = hmac.new(settings.session_secret.encode(), msg=val.encode(), digestmod=hashlib.sha256).hexdigest()
    return f"{val}:{digest}"


def _unsign(signed: str) -> Optional[str]:
    if not signed or ":" not in signed:
        return None
    val, digest = signed.rsplit(":", 1)
    expected = hmac.new(settings.session_secret.encode(), msg=val.encode(), digestmod=hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, digest):
        return val
    return None


def _set_auth_cookie(resp: Response, username: str) -> None:
    signed = _sign(username)
    resp.set_cookie(
        COOKIE_NAME,
        signed,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=False,  # set True behind TLS/HTTPS
        samesite="Lax",
        path="/",
    )


def _clear_auth_cookie(resp: Response) -> None:
    resp.delete_cookie(COOKIE_NAME, path="/")


def require_admin(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME)
    username = _unsign(cookie) if cookie else None
    if username != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})
    return username


@router.get("/login")
async def login_form(request: Request):
    return Response(
        content=(
            """
            <html><body>
            <h2>Admin login</h2>
            <form method='post'>
              <input name='username' placeholder='Username'/><br/>
              <input type='password' name='password' placeholder='Password'/><br/>
              <button type='submit'>Login</button>
            </form>
            </body></html>
            """
        ),
        media_type="text/html",
    )


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and password == settings.admin_password:
        resp = RedirectResponse(url="/admin/sites", status_code=status.HTTP_302_FOUND)
        _set_auth_cookie(resp, username)
        return resp
    return Response(content="Unauthorized", status_code=status.HTTP_401_UNAUTHORIZED)


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    _clear_auth_cookie(resp)
    return resp


@router.get("/sites")
async def admin_sites(request: Request, session: AsyncSession = Depends(get_db_session), user=Depends(require_admin)):
    svc = SiteService(session)
    sites = await svc.list(limit=500)
    rows = "".join(
        f"<tr><td>{s.name}</td><td>{s.url}</td><td>{'Yes' if s.is_active else 'No'}</td></tr>" for s in sites
    )
    return Response(
        content=(
            f"""
            <html><body>
            <div style='float:right'><a href='/admin/logout'>Logout</a></div>
            <h2>Sites</h2>
            <table border='1' cellpadding='6' cellspacing='0'>
              <tr><th>Name</th><th>URL</th><th>Active</th></tr>
              {rows or '<tr><td colspan="3">No sites</td></tr>'}
            </table>
            <h3>Add site</h3>
            <form method='post' action='/admin/sites'>
              <input name='name' placeholder='Name' required/>
              <input name='url' placeholder='https://example.com' required/>
              <input name='check_interval_sec' type='number' min='5' value='60' required/>
              <input name='timeout_ms' type='number' min='1000' value='5000' required/>
              <input name='retry_count' type='number' min='0' value='1' required/>
              <input name='retry_backoff_ms' type='number' min='0' value='500' required/>
              <input name='sla_target' type='number' min='0' max='100' value='99' />
              <button type='submit'>Add</button>
            </form>
            </body></html>
            """
        ),
        media_type="text/html",
    )


@router.post("/sites")
async def admin_add_site(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    user=Depends(require_admin),
    name: str = Form(...),
    url: str = Form(...),
    check_interval_sec: int = Form(...),
    timeout_ms: int = Form(...),
    retry_count: int = Form(...),
    retry_backoff_ms: int = Form(...),
    sla_target: int | None = Form(None),
):
    svc = SiteService(session)
    await svc.create(
        name=name,
        url=url,
        check_interval_sec=check_interval_sec,
        timeout_ms=timeout_ms,
        retry_count=retry_count,
        retry_backoff_ms=retry_backoff_ms,
        sla_target=sla_target,
    )
    return RedirectResponse(url="/admin/sites", status_code=status.HTTP_302_FOUND)
