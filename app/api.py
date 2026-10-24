from __future__ import annotations

import asyncio
import hmac
import html
import io
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import qrcode
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import __version__
from .config import settings
from .db import SessionLocal, get_session
from .models import (
    Advisor,
    AreaUser,
    Contact,
    Conversation,
    Handoff,
    HandoffEvent,
    Message,
    Order,
    Payment,
    PaymentEvent,
    WebhookEvent,
)
from .payments import verify_standard_webhook
from .runtime import whatsapp
from .sap import SapError, get_sap
from .services import catalog
from .services import advisors as advisor_service
from .services import area_rules
from .services import area_users
from .services import occasion_store
from .services import overview as overview_service
from .services import rule_simulator
from .services import feedback as feedback_service
from .services import handoffs
from .services import knowledge
from .services import native_commerce
from .services import refresh as refresh_service
from .services.ingest import ingest_inbound
from .services.orders import CheckoutError, confirm_payment
from .whatsapp import extract_order, extract_text, verify_signature

logger = logging.getLogger(__name__)
router = APIRouter()


class AreaRulePayload(BaseModel):
    area: str
    name: str
    rule_type: str
    condition: dict = {}
    action: dict = {}
    priority: int = 0
    status: str = "draft"
    valid_from: date | None = None
    valid_to: date | None = None


class AreaUserIn(BaseModel):
    username: str
    password: str
    area: str
    display_name: str | None = None


class AreaUserPatch(BaseModel):
    display_name: str | None = None
    area: str | None = None
    active: bool | None = None
    password: str | None = None


class PasswordChange(BaseModel):
    password: str


class OccasionPayload(BaseModel):
    name: str
    aliases: list[str] = []
    direct: list[str] = []
    exclude: list[str] = []
    exclude_categories: list[str] = []
    bridges: list[dict] = []
    area: str = "marketing"
    status: str = "draft"
    priority: int = 100
    valid_from: date | None = None
    valid_to: date | None = None


class SimulationPayload(BaseModel):
    query: str
    area: str = "ecommerce"

_redis_pool = None


async def _redis():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _redis_pool


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Token de administración inválido")


def require_internal_refresh(
    request: Request,
    x_internal_token: str = Header(default=""),
) -> None:
    """Solo el propio bot (localhost) puede refrescar un SKU."""
    if not settings.internal_refresh_token:
        raise HTTPException(
            status_code=503,
            detail="Refresco interno no configurado",
        )
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403,
            detail="El refresco interno solo acepta localhost",
        )
    if not hmac.compare_digest(
        x_internal_token, settings.internal_refresh_token
    ):
        raise HTTPException(status_code=401, detail="Token interno inválido")


async def require_area_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    token = request.cookies.get("area_session", "")
    username = advisor_service.parse_session(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Sesión de área requerida")
    user = await area_users.get_by_username(session, username)
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario de área inactivo")
    return {
        "username": user.username,
        "display_name": user.display_name,
        "area": user.area,
    }


async def require_advisor(
    request: Request,
    x_admin_token: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if settings.admin_token and x_admin_token == settings.admin_token:
        return {
            "username": "admin",
            "display_name": "Admin",
            "is_admin": True,
            "is_supervisor": True,
            "role": "admin",
            "on_duty": True,
        }
    token = request.cookies.get("advisor_session", "")
    username = advisor_service.parse_session(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Sesión de asesor requerida")
    advisor = await advisor_service.current_advisor(session, username)
    if advisor is None:
        raise HTTPException(status_code=401, detail="Asesor inactivo")
    role = advisor.role or ("admin" if advisor.is_admin else "agent")
    return {
        "username": advisor.username,
        "display_name": advisor.display_name,
        "is_admin": role == "admin",
        "is_supervisor": role in {"admin", "supervisor"},
        "role": role,
        "on_duty": advisor.on_duty,
    }


async def require_supervisor(
    advisor: dict = Depends(require_advisor),
) -> dict:
    if not advisor.get("is_supervisor"):
        raise HTTPException(status_code=403, detail="Requiere supervisor")
    return advisor


async def require_admin_role(
    advisor: dict = Depends(require_advisor),
) -> dict:
    if not advisor.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requiere administrador")
    return advisor


async def require_center_admin(
    advisor: dict = Depends(require_advisor),
) -> dict:
    """Admin del centro: sesión de asesor admin o token de administración."""
    if not advisor.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requiere administrador")
    return advisor


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/advisor/login", include_in_schema=False)
async def advisor_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/console/login", status_code=303)


@router.get("/advisor/login", response_class=HTMLResponse)
async def advisor_login_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingresar · ROHO</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f6f8;display:grid;place-items:center;min-height:100vh;margin:0}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:24px;width:320px;box-shadow:0 8px 30px #0001}
h1{font-size:20px;margin:0 0 16px}label{display:block;font-size:13px;margin:10px 0 4px;color:#374151}
input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #d1d5db;border-radius:8px}
button{width:100%;margin-top:16px;padding:11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:700;cursor:pointer}
.err{color:#b91c1c;font-size:13px;min-height:18px}
</style></head><body>
<form class="card" id="form">
  <h1>Bandeja ROHO</h1>
  <div class="err" id="err"></div>
  <label>Usuario</label><input id="username" autocomplete="username" required>
  <label>Contraseña</label><input id="password" type="password" autocomplete="current-password" required>
  <button>Ingresar</button>
</form>
<script>
document.getElementById('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('err'); err.textContent = '';
  const r = await fetch('/advisor/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username: document.getElementById('username').value,
                          password: document.getElementById('password').value})});
  if (!r.ok) { err.textContent = 'Usuario o contraseña incorrectos'; return; }
  window.location.href = '/admin/handoffs/view';
});
</script></body></html>"""
    )


@router.post("/advisor/login")
async def advisor_login(
    request: Request,
    payload: LoginIn,
    session: AsyncSession = Depends(get_session)
):
    advisor = await advisor_service.authenticate(
        session, payload.username, payload.password
    )
    if advisor is None:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    response = JSONResponse({"ok": True, "username": advisor.username})
    response.set_cookie(
        "advisor_session",
        advisor_service.make_session(advisor.username),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.advisor_session_hours * 3600,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/advisor/logout")
async def advisor_logout() -> RedirectResponse:
    response = RedirectResponse(url="/console/login", status_code=303)
    response.delete_cookie("advisor_session")
    return response


@router.get("/advisor/me")
async def advisor_me(advisor: dict = Depends(require_advisor)) -> dict:
    return advisor


@router.get("/advisor/duty")
async def advisor_duty(
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await advisor_service.on_duty_advisors(session)
    return {
        "on_duty": [
            {"username": row.username, "display_name": row.display_name}
            for row in rows
        ]
    }


@router.get("/advisor/team")
async def advisor_team(
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await advisor_service.list_advisors(session)
    return {
        "advisors": [
            {
                "username": row.username,
                "display_name": row.display_name,
                "on_duty": row.on_duty,
            }
            for row in rows
            if row.active
        ]
    }


@router.get("/advisor/events")
async def advisor_events(
    request: Request,
    advisor: dict = Depends(require_advisor),
):
    async def stream():
        last = ""
        ticks = 0
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            async with SessionLocal() as session:
                last_message = await session.scalar(
                    select(func.max(Message.created_at))
                )
                last_event = await session.scalar(
                    select(func.max(HandoffEvent.created_at))
                )
                rows = (
                    await session.execute(
                        select(
                            Handoff.status,
                            Handoff.assigned_to,
                            func.count(Handoff.id),
                        ).group_by(Handoff.status, Handoff.assigned_to)
                    )
                ).all()
                fingerprint = json.dumps(
                    {
                        "message": last_message.isoformat()
                        if last_message
                        else None,
                        "event": last_event.isoformat()
                        if last_event
                        else None,
                        "handoffs": sorted(
                            [list(map(str, row)) for row in rows]
                        ),
                    },
                    sort_keys=True,
                )
            if fingerprint != last:
                yield "event: refresh\ndata: {}\n\n"
                last = fingerprint
            ticks += 1
            if ticks % 8 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class AdvisorIn(BaseModel):
    username: str
    password: str
    display_name: str = ""
    is_admin: bool = False
    role: str | None = None
    on_duty: bool = True


class AdvisorPatch(BaseModel):
    display_name: str | None = None
    active: bool | None = None
    is_admin: bool | None = None
    role: str | None = None
    on_duty: bool | None = None
    password: str | None = None


@router.get("/survey/{token}", response_class=HTMLResponse)
async def survey_page(token: str, session: AsyncSession = Depends(get_session)):
    survey = await handoffs.get_survey(session, token)
    if survey is None:
        return HTMLResponse("<h1>Encuesta no encontrada</h1>", status_code=404)
    if survey.answered_at is not None:
        return HTMLResponse("<h1>¡Gracias!</h1><p>Ya registramos tu respuesta.</p>")
    return HTMLResponse(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Encuesta ROHO</title>
<style>body{{font-family:system-ui;background:#f8fafc;display:grid;place-items:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px;max-width:380px;text-align:center}}
button{{font-size:28px;margin:4px;border:0;background:#f1f5f9;border-radius:10px;padding:8px 12px;cursor:pointer}}
button:hover{{background:#fee2e2}}textarea{{width:100%;box-sizing:border-box;margin-top:14px;padding:10px;border:1px solid #cbd5e1;border-radius:8px}}
</style></head><body><div class="card"><h2>¿Cómo fue la atención?</h2>
<p>Tu opinión nos ayuda a mejorar.</p>
<div>
<button onclick="rate(1)">😞</button><button onclick="rate(2)">🙁</button><button onclick="rate(3)">😐</button><button onclick="rate(4)">🙂</button><button onclick="rate(5)">😍</button>
</div><textarea id="comment" rows="3" placeholder="Comentario opcional"></textarea>
<p id="status"></p></div>
<script>
async function rate(value) {{
  const r = await fetch('/survey/{token}', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{rating:value,comment:document.getElementById('comment').value}})}});
  document.body.innerHTML = r.ok ? '<div class="card"><h2>¡Gracias!</h2><p>Registramos tu respuesta.</p></div>' : '<div class="card"><h2>No se pudo registrar</h2></div>';
}}
</script></body></html>"""
    )


@router.post("/survey/{token}")
async def survey_answer(
    token: str, payload: SurveyIn, session: AsyncSession = Depends(get_session)
):
    result = await handoffs.answer_survey(
        session, token, payload.rating, payload.comment
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")
    return result
@router.get("/admin/advisors/view", response_class=HTMLResponse)
async def advisors_view() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agentes · ROHO</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#111827}
header{background:#0f172a;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
header a{color:#cbd5e1;text-decoration:none;margin-left:14px}
main{max-width:1050px;margin:22px auto;padding:0 16px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:12px}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.badge{font-size:12px;font-weight:700;padding:3px 8px;border-radius:999px;background:#e5e7eb}
.badge.on{background:#dcfce7;color:#166534}.badge.off{background:#f3f4f6;color:#6b7280}
input,select{padding:8px;border:1px solid #d1d5db;border-radius:8px;box-sizing:border-box}
button{border:0;border-radius:8px;padding:8px 12px;background:#111827;color:#fff;font-weight:600;cursor:pointer;margin:4px 4px 0 0}
button.secondary{background:#e5e7eb;color:#111827}
button.danger{background:#b91c1c}
.err{color:#b91c1c;font-size:13px}
</style></head><body>
<header><strong>Agentes ROHO</strong><div><a href="/admin/handoffs/view">Bandeja</a><a href="/advisor/logout">Salir</a></div></header>
<main>
  <p class="err" id="err"></p>
  <div class="card">
    <h3>Nuevo agente</h3>
    <form id="create">
      <input id="username" placeholder="usuario" required>
      <input id="display_name" placeholder="nombre visible" required>
      <input id="password" type="password" placeholder="contraseña" required>
      <label><input type="checkbox" id="is_admin"> administrador</label>
      <label><input type="checkbox" id="on_duty" checked> de guardia</label>
      <button>Crear</button>
    </form>
  </div>
  <div id="list">Cargando…</div>
</main>
<script>
let me = null;
async function api(path, opts={}) {
  const r = await fetch(path, Object.assign({}, opts, {credentials:'same-origin', headers:Object.assign({'Content-Type':'application/json'}, opts.headers||{})}));
  if (r.status===401) { location.href='/advisor/login'; throw new Error('sin sesión'); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function load() {
  const box=document.getElementById('list');
  try {
    me = await api('/advisor/me');
    if (!me.is_admin) { location.href='/admin/handoffs/view'; return; }
    const data = await api('/admin/advisors');
    box.innerHTML = data.advisors.map(a => `<div class="card"><div class="row">
      <div><strong>${esc(a.display_name)}</strong><div class="muted">${esc(a.username)}</div></div>
      <div><span class="badge ${a.on_duty?'on':'off'}">${a.on_duty?'de guardia':'fuera'}</span>
      <span class="badge">${a.is_admin?'admin':'agente'}</span>
      <span class="badge ${a.active?'on':'off'}">${a.active?'activo':'inactivo'}</span></div></div>
      <button class="secondary" onclick="patch('${a.id}',{on_duty:${!a.on_duty}})">${a.on_duty?'Quitar guardia':'Poner guardia'}</button>
      <button class="secondary" onclick="patch('${a.id}',{active:${!a.active}})">${a.active?'Desactivar':'Activar'}</button>
      <button class="secondary" onclick="patch('${a.id}',{is_admin:${!a.is_admin}})">${a.is_admin?'Quitar admin':'Hacer admin'}</button>
      <button class="secondary" onclick="reset('${a.id}')">Cambiar clave</button>
    </div>`).join('');
  } catch(e){ box.textContent='Error: '+e.message; }
}
async function patch(id, body) { await api('/admin/advisors/'+id,{method:'PATCH',body:JSON.stringify(body)}); load(); }
async function reset(id) { const p=prompt('Nueva contraseña'); if(!p) return; await patch(id,{password:p}); alert('Contraseña actualizada'); }
document.getElementById('create').addEventListener('submit', async (e)=>{
  e.preventDefault(); const err=document.getElementById('err'); err.textContent='';
  try { await api('/admin/advisors',{method:'POST',body:JSON.stringify({
    username:document.getElementById('username').value,
    display_name:document.getElementById('display_name').value,
    password:document.getElementById('password').value,
    is_admin:document.getElementById('is_admin').checked,
    on_duty:document.getElementById('on_duty').checked
  })}); e.target.reset(); document.getElementById('on_duty').checked=true; load(); }
  catch(ex){ err.textContent='No se pudo crear: '+ex.message; }
});
load();
</script></body></html>"""
    )


@router.get(
    "/admin/metrics",
    dependencies=[Depends(require_supervisor)],
)
async def admin_metrics(
    days: int = 30,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return {
        "ok": True,
        "days": days,
        "advisors": await handoffs.advisor_metrics(session, days),
    }


@router.get(
    "/admin/advisors",
    dependencies=[Depends(require_admin_role)],
)
async def admin_advisors(
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await advisor_service.list_advisors(session)
    return {
        "ok": True,
        "advisors": [
            {
                "id": advisor.id,
                "username": advisor.username,
                "display_name": advisor.display_name,
                "active": advisor.active,
                "is_admin": advisor.is_admin,
                "role": advisor.role,
                "on_duty": advisor.on_duty,
            }
            for advisor in rows
        ],
    }


@router.post(
    "/admin/advisors",
    dependencies=[Depends(require_admin_role)],
)
async def admin_advisor_create(
    payload: AdvisorIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        advisor = await advisor_service.create_advisor(
            session,
            payload.username,
            payload.password,
            payload.display_name or None,
            is_admin=payload.is_admin,
            role=payload.role,
        )
        advisor.on_duty = payload.on_duty
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    return {"ok": True, "id": advisor.id}


@router.patch(
    "/admin/advisors/{advisor_id}",
    dependencies=[Depends(require_admin_role)],
)
async def admin_advisor_patch(
    advisor_id: str,
    payload: AdvisorPatch,
    session: AsyncSession = Depends(get_session),
) -> dict:
    advisor = await session.get(Advisor, advisor_id)
    if advisor is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    if payload.display_name is not None:
        advisor.display_name = payload.display_name[:120]
    if payload.active is not None:
        advisor.active = payload.active
    if payload.is_admin is not None:
        advisor.is_admin = payload.is_admin
        advisor.role = "admin" if payload.is_admin else "agent"
    if payload.role is not None:
        if payload.role not in {"admin", "supervisor", "agent"}:
            raise HTTPException(status_code=400, detail="Rol inválido")
        advisor.role = payload.role
        advisor.is_admin = payload.role == "admin"
    if payload.on_duty is not None:
        advisor.on_duty = payload.on_duty
    if payload.password:
        advisor.password_hash = advisor_service.hash_password(payload.password)
    await session.commit()
    return {"ok": True}


@router.get(
    "/admin/feedback/summary",
    dependencies=[Depends(require_admin)],
)
async def admin_feedback_summary(
    session: AsyncSession = Depends(get_session),
) -> dict:
    return {
        "ok": True,
        "summary": await feedback_service.feedback_summary(session),
        "pending": await feedback_service.pending_requests(session),
    }


@router.get(
    "/admin/feedback/pending",
    dependencies=[Depends(require_admin)],
)
async def admin_feedback_pending(
    session: AsyncSession = Depends(get_session),
) -> dict:
    return {"ok": True, "pending": await feedback_service.pending_requests(session)}


@router.get(
    "/admin/feedback/complaints",
    dependencies=[Depends(require_admin)],
)
async def admin_feedback_complaints(
    include_acknowledged: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return {
        "ok": True,
        "complaints": await feedback_service.complaints(
            session, include_acknowledged=include_acknowledged
        ),
    }


@router.post(
    "/admin/feedback/{feedback_id}/acknowledge",
    dependencies=[Depends(require_admin)],
)
async def admin_feedback_acknowledge(
    feedback_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await feedback_service.acknowledge(session, feedback_id)


@router.get("/admin/area-rules/view", response_class=HTMLResponse)
async def admin_area_rules_view() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reglas por área · ROHO</title>
<style>
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f6f7f9;color:#17212b}
header{background:#0f172a;color:#fff;padding:14px 22px}
main{max-width:1100px;margin:20px auto;padding:0 16px}
.card{background:#fff;border:1px solid #dde3ea;border-radius:10px;padding:16px;margin-bottom:16px}
label{display:block;font-size:13px;font-weight:600;margin:10px 0 4px}
input,select,textarea{width:100%;padding:9px;border:1px solid #cbd5e1;border-radius:7px;box-sizing:border-box}
textarea{min-height:70px;font-family:ui-monospace,monospace;font-size:12px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{padding:9px 13px;border:0;border-radius:7px;cursor:pointer;margin:4px 4px 0 0}
.primary{background:#0f172a;color:#fff}.ok{background:#0f766e;color:#fff}.danger{background:#b91c1c;color:#fff}
.muted{color:#64748b;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}
.badge{padding:2px 7px;border-radius:20px;background:#e2e8f0;font-size:11px}
.published{background:#ccfbf1;color:#115e59}.draft{background:#fef3c7;color:#92400e}
pre{white-space:pre-wrap;margin:0;font-size:11px}
</style>
</head>
<body>
<header><strong>ROHO · Reglas por área</strong> <span class="muted">Centro de instrucciones del bot</span></header>
<main>
<div class="card">
  <label>Token de administración</label>
  <div class="row"><input id="token" type="password" placeholder="X-Admin-Token"><button class="primary" onclick="saveToken()">Guardar token</button></div>
  <p class="muted">El token se guarda solo en este navegador. No se muestra en la URL.</p>
</div>

<div class="card">
  <h3 id="formTitle">Nueva regla</h3>
  <input id="ruleId" type="hidden">
  <div class="row">
    <div><label>Área</label><select id="area"><option>ecommerce</option><option>calidad</option><option>marketing</option><option>operaciones</option><option>general</option></select></div>
    <div><label>Tipo</label><select id="ruleType"><option>brand_priority</option><option>return_flow</option><option>response_rule</option><option>required_questions</option></select></div>
  </div>
  <label>Nombre</label><input id="name" placeholder="Ej: Priorizar LG en heladeras">
  <div class="row">
    <div><label>Prioridad</label><input id="priority" type="number" value="100"></div>
    <div><label>Estado</label><select id="status"><option>draft</option><option>published</option><option>archived</option></select></div>
  </div>
  <label>Condición (JSON)</label><textarea id="condition">{"category":"heladera"}</textarea>
  <label>Acción (JSON)</label><textarea id="action">{"brand":"LG"}</textarea>
  <button class="primary" onclick="saveRule()">Guardar</button>
  <button onclick="resetForm()">Limpiar</button>
  <p id="msg" class="muted"></p>
</div>

<div class="card">
  <h3>Reglas cargadas</h3>
  <table><thead><tr><th>Área</th><th>Nombre</th><th>Tipo</th><th>Prioridad</th><th>Estado</th><th>Condición / Acción</th><th></th></tr></thead><tbody id="rows"></tbody></table>
</div>
</main>
<script>
const API='/admin/area-rules';
let cache=[];
function token(){return localStorage.getItem('roho_admin_token')||''}
function saveToken(){localStorage.setItem('roho_admin_token',document.getElementById('token').value);load()}
function hdr(){return {'Content-Type':'application/json','X-Admin-Token':token()}}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path,opts){const r=await fetch(path,Object.assign({headers:hdr()},opts||{}));const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||('HTTP '+r.status));return b}
async function load(){try{const b=await api(API);cache=b.rules||[];document.getElementById('rows').innerHTML=cache.map(r=>`<tr><td>${esc(r.area)}</td><td>${esc(r.name)}</td><td>${esc(r.rule_type)}</td><td>${r.priority}</td><td><span class="badge ${r.status}">${esc(r.status)}</span></td><td><pre>${esc(JSON.stringify(r.condition))}\n${esc(JSON.stringify(r.action))}</pre></td><td><button onclick="editRule('${r.id}')">Editar</button>${r.status!=='published'?`<button class="ok" onclick="publishRule('${r.id}')">Publicar</button>`:''}<button class="danger" onclick="deleteRule('${r.id}')">Eliminar</button></td></tr>`).join('');document.getElementById('msg').textContent=''}catch(e){document.getElementById('msg').textContent=e.message}}
function editRule(id){const r=cache.find(x=>x.id===id);if(!r)return;document.getElementById('ruleId').value=r.id;document.getElementById('area').value=r.area;document.getElementById('ruleType').value=r.rule_type;document.getElementById('name').value=r.name;document.getElementById('priority').value=r.priority;document.getElementById('status').value=r.status;document.getElementById('condition').value=JSON.stringify(r.condition,null,2);document.getElementById('action').value=JSON.stringify(r.action,null,2);document.getElementById('formTitle').textContent='Editar regla';window.scrollTo({top:0,behavior:'smooth'})}
async function saveRule(){try{const id=document.getElementById('ruleId').value;const body={area:document.getElementById('area').value,name:document.getElementById('name').value,rule_type:document.getElementById('ruleType').value,priority:Number(document.getElementById('priority').value),status:document.getElementById('status').value,condition:JSON.parse(document.getElementById('condition').value||'{}'),action:JSON.parse(document.getElementById('action').value||'{}')};await api(id?API+'/'+id:API,{method:id?'PUT':'POST',body:JSON.stringify(body)});document.getElementById('msg').textContent='Guardado';resetForm();await load()}catch(e){document.getElementById('msg').textContent=e.message}}
async function publishRule(id){try{await api(API+'/'+id+'/publish',{method:'POST'});await load()}catch(e){document.getElementById('msg').textContent=e.message}}
async function deleteRule(id){if(!confirm('¿Eliminar esta regla?'))return;try{await api(API+'/'+id,{method:'DELETE'});await load()}catch(e){document.getElementById('msg').textContent=e.message}}
function resetForm(){document.getElementById('ruleId').value='';document.getElementById('name').value='';document.getElementById('priority').value=100;document.getElementById('status').value='draft';document.getElementById('condition').value='{"category":"heladera"}';document.getElementById('action').value='{"brand":"LG"}';document.getElementById('formTitle').textContent='Nueva regla'}
document.getElementById('token').value=token();load();
</script>
</body>
</html>"""
    )


@router.get("/admin/center", response_class=HTMLResponse)
async def admin_center_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Centro de administración · ROHO</title>
<style>
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f6f7f9;color:#17212b}
header{background:#0f172a;color:#fff;padding:14px 22px}
main{max-width:1000px;margin:20px auto;padding:0 16px}
.card{background:#fff;border:1px solid #dde3ea;border-radius:10px;padding:16px;margin-bottom:16px}
label{display:block;font-size:13px;font-weight:600;margin:10px 0 4px}
input,select{width:100%;box-sizing:border-box;padding:9px;border:1px solid #cbd5e1;border-radius:7px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{padding:9px 13px;border:0;border-radius:7px;cursor:pointer;margin:4px 4px 0 0}
.primary{background:#0f172a;color:#fff}.ok{background:#0f766e;color:#fff}.danger{background:#b91c1c;color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}
.badge{padding:2px 7px;border-radius:20px;background:#e2e8f0;font-size:11px}
.muted{color:#64748b;font-size:13px}
</style></head><body>
<header><strong>ROHO · Centro de administración</strong></header>
<main>
<div id="loginCard" class="card">
<h3>Ingresar como administrador</h3>
<div class="row"><div><label>Usuario</label><input id="loginUser" autocomplete="username"></div><div><label>Contraseña</label><input id="loginPass" type="password" autocomplete="current-password"></div></div>
<button class="primary" onclick="login()">Ingresar</button>
<p class="muted">Usá una cuenta con rol administrador.</p>
</div>
<div id="app" style="display:none">
<div class="card">
<h3>Crear usuario de área</h3>
<div class="row"><div><label>Usuario</label><input id="username" placeholder="ecommerce"></div><div><label>Nombre visible</label><input id="display" placeholder="Encargado de Ecommerce"></div></div>
<div class="row"><div><label>Área</label><select id="area"><option>ecommerce</option><option>calidad</option><option>marketing</option><option>operaciones</option><option>general</option></select></div><div><label>Contraseña</label><input id="password" type="password" placeholder="mínimo 8 caracteres"></div></div>
<button class="primary" onclick="createUser()">Crear usuario</button>
<p id="msg" class="muted"></p>
</div>
<div class="card"><h3>Usuarios de área</h3>
<table><thead><tr><th>Usuario</th><th>Nombre</th><th>Área</th><th>Estado</th></tr></thead><tbody id="users"></tbody></table>
<p><a href="/admin/area-rules/view">Ir al administrador de reglas →</a> · <a href="/advisor/logout">Salir</a></p>
</div>
</div>
</main>
<script>
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function api(path,opts){const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opts||{}));const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||('HTTP '+r.status));return b}
async function me(){try{const m=await api('/advisor/me');if(!m.is_admin){document.getElementById('msg').textContent='La cuenta no tiene rol administrador';return}document.getElementById('loginCard').style.display='none';document.getElementById('app').style.display='block';await load()}catch(e){document.getElementById('loginCard').style.display='block';document.getElementById('app').style.display='none'}}
async function login(){try{const u=document.getElementById('loginUser').value,p=document.getElementById('loginPass').value;const r=await fetch('/advisor/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});if(!r.ok)throw new Error('Usuario o contraseña incorrectos');await me()}catch(e){document.getElementById('msg').textContent=e.message}}
async function load(){try{const b=await api('/admin/area-users');document.getElementById('users').innerHTML=(b.users||[]).map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.display_name)}</td><td>${esc(u.area)}</td><td><span class="badge">${u.active?'activo':'inactivo'}</span></td></tr>`).join('')}catch(e){document.getElementById('msg').textContent=e.message}}
async function createUser(){try{const body={username:document.getElementById('username').value,password:document.getElementById('password').value,display_name:document.getElementById('display').value,area:document.getElementById('area').value};await api('/admin/area-users',{method:'POST',body:JSON.stringify(body)});document.getElementById('msg').textContent='Usuario creado';document.getElementById('username').value='';document.getElementById('password').value='';await load()}catch(e){document.getElementById('msg').textContent=e.message}}
me();
</script></body></html>"""
    )


@router.get("/areas/panel", response_class=HTMLResponse)
async def area_rules_panel() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mis reglas · ROHO</title>
<style>
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f6f7f9;color:#17212b}
header{background:#0f172a;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
main{max-width:1000px;margin:20px auto;padding:0 16px}
.card{background:#fff;border:1px solid #dde3ea;border-radius:12px;padding:18px;margin-bottom:16px}
label{display:block;font-size:13px;font-weight:600;margin:10px 0 4px}
input,select,textarea{width:100%;box-sizing:border-box;padding:9px;border:1px solid #cbd5e1;border-radius:7px}
textarea{min-height:70px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{padding:9px 13px;border:0;border-radius:7px;cursor:pointer;margin:4px 4px 0 0}
.primary{background:#0f172a;color:#fff}.ok{background:#0f766e;color:#fff}.danger{background:#b91c1c;color:#fff}.ghost{background:#e2e8f0}
.muted{color:#64748b;font-size:13px}.qrow{border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin:8px 0}
.badge{padding:2px 7px;border-radius:20px;background:#e2e8f0;font-size:11px}.published{background:#ccfbf1;color:#115e59}.draft{background:#fef3c7;color:#92400e}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;margin:0;font-size:11px}
</style></head><body>
<header><strong id="who">Mis reglas</strong><span><a style="color:#cbd5e1" href="/areas/logout">Salir</a></span></header>
<main>
<div class="card">
<h3 id="formTitle">Nueva regla</h3>
<input id="ruleId" type="hidden">
<label>¿Qué querés hacer?</label>
<select id="kind" onchange="toggleKind()">
<option value="brand_priority">Priorizar una marca cuando pregunten por una categoría</option>
<option value="return_flow">Crear un flujo de preguntas para devoluciones</option>
</select>
<label>Nombre de la regla</label><input id="name" placeholder="Ej: Priorizar LG en heladeras">
<div id="brandBox">
  <div class="row"><div><label>Categoría</label><input id="category" placeholder="heladera, televisor, colchón..."></div>
  <div><label>Marca que querés priorizar</label><input id="brand" placeholder="LG"></div></div>
</div>
<div id="flowBox" style="display:none">
  <label>Preguntas del flujo (una por una)</label>
  <div id="questions"></div>
  <button class="ghost" onclick="addQuestion()">+ Agregar pregunta</button>
  <p class="muted">Marcá “Debe responder Sí” para que esa respuesta sea obligatoria.</p>
</div>
<div class="row"><div><label>Prioridad</label><input id="priority" type="number" value="100"></div>
<div><label>Estado</label><select id="status"><option>draft</option><option>published</option></select></div></div>
<button class="primary" onclick="saveRule()">Guardar regla</button>
<button class="ghost" onclick="resetForm()">Limpiar</button>
<p id="msg" class="muted"></p>
</div>
<div class="card"><h3>Mis reglas cargadas</h3>
<table><thead><tr><th>Nombre</th><th>Tipo</th><th>Detalle</th><th>Estado</th><th></th></tr></thead><tbody id="rows"></tbody></table>
</div>
</main>
<script>
let me=null, cache=[];
async function api(path,opts){const r=await fetch(path,Object.assign({headers:{'Content-Type':'application/json'}},opts||{}));if(r.status===401){location.href='/areas/login';throw new Error('sin sesión')}const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.detail||('HTTP '+r.status));return b}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toggleKind(){const flow=document.getElementById('kind').value==='return_flow';document.getElementById('brandBox').style.display=flow?'none':'block';document.getElementById('flowBox').style.display=flow?'block':'none'}
function addQuestion(text='',key='',requireYes=false){const box=document.getElementById('questions');const row=document.createElement('div');row.className='qrow';row.innerHTML=`<div class="row"><div><label>Pregunta</label><input class="qtext" value="${esc(text)}" placeholder="¿Tenés la factura original?"></div><div><label>Clave</label><input class="qkey" value="${esc(key)}" placeholder="factura"></div></div><label><input type="checkbox" class="qreq" ${requireYes?'checked':''}> Debe responder Sí</label> <button class="danger" onclick="this.closest('.qrow').remove()">Quitar</button>`;box.appendChild(row)}
function questionsFromForm(){return [...document.querySelectorAll('.qrow')].map(r=>({text:r.querySelector('.qtext').value.trim(),key:r.querySelector('.qkey').value.trim()||r.querySelector('.qtext').value.trim().toLowerCase().replace(/[^a-z0-9]+/g,'_'),type:'yes_no',_req:r.querySelector('.qreq').checked})).filter(q=>q.text)}
function resetForm(){document.getElementById('ruleId').value='';document.getElementById('name').value='';document.getElementById('category').value='';document.getElementById('brand').value='';document.getElementById('priority').value=100;document.getElementById('status').value='draft';document.getElementById('kind').value='brand_priority';document.getElementById('questions').innerHTML='';addQuestion();toggleKind();document.getElementById('formTitle').textContent='Nueva regla'}
async function load(){me=await api('/areas/me');document.getElementById('who').textContent='Reglas de '+me.area+' · '+me.display_name;const b=await api('/areas/rules');cache=b.rules||[];document.getElementById('rows').innerHTML=cache.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.rule_type)}</td><td>${detail(r)}</td><td><span class="badge ${r.status}">${esc(r.status)}</span></td><td><button onclick="editRule('${r.id}')">Editar</button>${r.status!=='published'?`<button class="ok" onclick="publishRule('${r.id}')">Publicar</button>`:''}<button class="danger" onclick="deleteRule('${r.id}')">Eliminar</button></td></tr>`).join('')}
function detail(r){if(r.rule_type==='brand_priority')return `Categoría: ${esc(r.condition.category||'')} → ${esc(r.action.brand||'')}`;if(r.rule_type==='return_flow')return `${(r.action.questions||[]).length} preguntas`;return esc(JSON.stringify(r.condition))+' → '+esc(JSON.stringify(r.action))}
function editRule(id){const r=cache.find(x=>x.id===id);if(!r)return;document.getElementById('ruleId').value=r.id;document.getElementById('name').value=r.name;document.getElementById('priority').value=r.priority;document.getElementById('status').value=r.status;document.getElementById('kind').value=r.rule_type==='return_flow'?'return_flow':'brand_priority';toggleKind();if(r.rule_type==='brand_priority'){document.getElementById('category').value=r.condition.category||'';document.getElementById('brand').value=r.action.brand||''}else{document.getElementById('questions').innerHTML='';for(const q of r.action.questions||[])addQuestion(q.text||'',q.key||'',!!(r.action.requirements||{})[q.key])}document.getElementById('formTitle').textContent='Editar regla';window.scrollTo({top:0,behavior:'smooth'})}
async function saveRule(){try{const id=document.getElementById('ruleId').value;const kind=document.getElementById('kind').value;const name=document.getElementById('name').value.trim();if(!name)throw new Error('Poné un nombre a la regla');let condition={},action={};if(kind==='brand_priority'){const cat=document.getElementById('category').value.trim();const brand=document.getElementById('brand').value.trim();if(!cat||!brand)throw new Error('Completá categoría y marca');condition={category:cat};action={brand}}else{const qs=questionsFromForm();if(!qs.length)throw new Error('Agregá al menos una pregunta');action={questions:qs.map(q=>({key:q.key,text:q.text,type:'yes_no'})),requirements:Object.fromEntries(qs.filter(q=>q._req).map(q=>[q.key,true]))};condition={intent:'devolucion'}}const body={area:'general',name,rule_type:kind,condition,action,priority:Number(document.getElementById('priority').value),status:document.getElementById('status').value};await api(id?'/areas/rules/'+id:'/areas/rules',{method:id?'PUT':'POST',body:JSON.stringify(body)});document.getElementById('msg').textContent='Guardado';resetForm();await load()}catch(e){document.getElementById('msg').textContent=e.message}}
async function publishRule(id){try{await api('/areas/rules/'+id+'/publish',{method:'POST'});await load()}catch(e){document.getElementById('msg').textContent=e.message}}
async function deleteRule(id){if(!confirm('¿Eliminar esta regla?'))return;try{await api('/areas/rules/'+id,{method:'DELETE'});await load()}catch(e){document.getElementById('msg').textContent=e.message}}
resetForm();load();
</script></body></html>"""
    )


@router.get("/areas/login", include_in_schema=False)
async def area_login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/console/login?mode=area", status_code=303)


@router.get("/areas/login", response_class=HTMLResponse)
async def area_login_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingresar · Reglas por área</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f6f8;display:grid;place-items:center;min-height:100vh;margin:0}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:24px;width:330px;box-shadow:0 8px 30px #0001}
h1{font-size:20px;margin:0 0 6px}label{display:block;font-size:13px;margin:12px 0 4px;color:#374151}
input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #d1d5db;border-radius:8px}
button{width:100%;margin-top:16px;padding:11px;border:0;border-radius:8px;background:#111827;color:#fff;font-weight:700;cursor:pointer}
#err{color:#b91c1c;font-size:13px;margin-top:10px}
</style></head><body><div class="card">
<h1>Reglas por área</h1>
<p class="muted">Ingresá con el usuario de tu área.</p>
<label>Usuario</label><input id="username" autocomplete="username">
<label>Contraseña</label><input id="password" type="password" autocomplete="current-password">
<button id="go">Ingresar</button><div id="err"></div>
</div><script>
document.getElementById('go').onclick=async()=>{
  const r=await fetch('/areas/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value,password:document.getElementById('password').value})});
  if(!r.ok){document.getElementById('err').textContent='Usuario o contraseña incorrectos';return}
  location.href='/areas/panel';
};
</script></body></html>"""
    )


@router.post("/areas/login")
async def area_login(
    request: Request,
    payload: LoginIn,
    session: AsyncSession = Depends(get_session),
):
    user = await area_users.authenticate(
        session, payload.username, payload.password
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    response = JSONResponse({"ok": True, "area": user.area})
    response.set_cookie(
        "area_session",
        advisor_service.make_session(user.username),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=settings.advisor_session_hours * 3600,
    )
    return response


@router.get("/areas/logout")
async def area_logout() -> RedirectResponse:
    response = RedirectResponse(url="/console/login?mode=area", status_code=303)
    response.delete_cookie("area_session")
    return response


@router.get("/auth/me")
async def auth_me(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Resuelve la sesión una sola vez: admin/asesor o usuario de área."""
    advisor_token = request.cookies.get("advisor_session", "")
    advisor_name = (
        advisor_service.parse_session(advisor_token) if advisor_token else None
    )
    if advisor_name:
        advisor = await advisor_service.current_advisor(session, advisor_name)
        if advisor is not None:
            role = advisor.role or ("admin" if advisor.is_admin else "agent")
            return {
                "kind": "advisor",
                "advisor": {
                    "username": advisor.username,
                    "display_name": advisor.display_name,
                    "is_admin": role == "admin",
                    "is_supervisor": role in {"admin", "supervisor"},
                    "role": role,
                    "on_duty": advisor.on_duty,
                },
            }
    area_token = request.cookies.get("area_session", "")
    area_name = (
        advisor_service.parse_session(area_token) if area_token else None
    )
    if area_name:
        user = await area_users.get_by_username(session, area_name)
        if user is not None:
            return {
                "kind": "area",
                "area": {
                    "username": user.username,
                    "display_name": user.display_name,
                    "area": user.area,
                },
            }
    raise HTTPException(status_code=401, detail="Sesión requerida")


@router.get("/areas/me")
async def area_me(user: dict = Depends(require_area_user)) -> dict:
    return user


@router.post("/areas/rules/simulate")
async def area_rules_simulate(
    payload: SimulationPayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await rule_simulator.simulate(
        session, query=payload.query, area=user["area"]
    )


@router.post(
    "/admin/rules/simulate",
    dependencies=[Depends(require_center_admin)],
)
async def admin_rules_simulate(
    payload: SimulationPayload,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await rule_simulator.simulate(
        session, query=payload.query, area=payload.area
    )


@router.get("/areas/rules")
async def area_rules_list(
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await area_rules.list_rules(session, area=user["area"])
    return {"ok": True, "area": user["area"], "rules": [area_rules.to_dict(r) for r in rows]}


@router.post("/areas/rules")
async def area_rule_create(
    payload: AreaRulePayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        rule = await area_rules.create_rule(
            session,
            area=user["area"],
            name=payload.name,
            rule_type=payload.rule_type,
            condition=payload.condition,
            action=payload.action,
            priority=payload.priority,
            status=payload.status,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=user["username"],
        )
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.put("/areas/rules/{rule_id}")
async def area_rule_update(
    rule_id: str,
    payload: AreaRulePayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None or rule.area != user["area"]:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    try:
        rule = await area_rules.update_rule(
            session,
            rule,
            name=payload.name,
            rule_type=payload.rule_type,
            condition=payload.condition,
            action=payload.action,
            priority=payload.priority,
            status=payload.status,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=user["username"],
        )
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.post("/areas/rules/{rule_id}/publish")
async def area_rule_publish(
    rule_id: str,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None or rule.area != user["area"]:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    rule = await area_rules.set_status(
        session, rule, "published", changed_by=user["username"]
    )
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.delete("/areas/rules/{rule_id}")
async def area_rule_delete(
    rule_id: str,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None or rule.area != user["area"]:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    await area_rules.delete_rule(session, rule)
    return {"ok": True}


@router.get(
    "/admin/area-users",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_users(session: AsyncSession = Depends(get_session)) -> dict:
    rows = await area_users.list_users(session)
    return {
        "ok": True,
        "users": [
            {
                "id": row.id,
                "username": row.username,
                "display_name": row.display_name,
                "area": row.area,
                "active": row.active,
            }
            for row in rows
        ],
    }


@router.post(
    "/admin/area-users",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_user_create(
    payload: AreaUserIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        user = await area_users.create_user(
            session,
            username=payload.username,
            password=payload.password,
            area=payload.area,
            display_name=payload.display_name,
        )
    except area_users.AreaUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "id": user.id, "area": user.area}


@router.patch(
    "/admin/area-users/{user_id}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_user_patch(
    user_id: str,
    payload: AreaUserPatch,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await session.get(AreaUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    try:
        user = await area_users.update_user(
            session,
            user,
            display_name=payload.display_name,
            area=payload.area,
            active=payload.active,
            password=payload.password,
        )
    except area_users.AreaUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "area": user.area,
        "active": user.active,
    }


@router.post("/areas/me/password")
async def area_change_password(
    payload: PasswordChange,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    area_user = await area_users.get_by_username(session, user["username"])
    if area_user is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    try:
        await area_users.update_user(
            session, area_user, password=payload.password
        )
    except area_users.AreaUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get(
    "/admin/area-rules/{rule_id}/versions",
    dependencies=[Depends(require_center_admin)],
)
async def admin_rule_versions(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    versions = await area_rules.list_versions(session, rule_id)
    return {
        "ok": True,
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "changed_by": row.changed_by,
                "created_at": row.created_at.isoformat()
                if row.created_at
                else None,
                "snapshot": row.snapshot or {},
            }
            for row in versions
        ],
    }


@router.post(
    "/admin/area-rules/{rule_id}/rollback/{version}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_rule_rollback(
    rule_id: str,
    version: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    try:
        rule = await area_rules.rollback_rule(session, rule, version)
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.get("/areas/rules/{rule_id}/versions")
async def area_rule_versions(
    rule_id: str,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None or rule.area != user["area"]:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    versions = await area_rules.list_versions(session, rule_id)
    return {
        "ok": True,
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "changed_by": row.changed_by,
                "created_at": row.created_at.isoformat()
                if row.created_at
                else None,
                "snapshot": row.snapshot or {},
            }
            for row in versions
        ],
    }


@router.post("/areas/rules/{rule_id}/rollback/{version}")
async def area_rule_rollback(
    rule_id: str,
    version: int,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None or rule.area != user["area"]:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    try:
        rule = await area_rules.rollback_rule(
            session, rule, version, changed_by=user["username"]
        )
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.post("/areas/occasions/simulate")
async def area_occasions_simulate(
    payload: SimulationPayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Prueba qué ocasión detecta el bot con un mensaje real.

    Sirve para revisar los términos antes de publicar una campaña.
    """
    key, event = await occasion_store.resolve(session, payload.query)
    detected = None
    matched = None
    if event is not None:
        folded = (payload.query or "").lower()
        for alias in event.get("aliases") or [event.get("label", key)]:
            if alias and str(alias).lower() in folded:
                matched = str(alias)
                break
        detected = {
            "slug": key,
            "label": event.get("label") or key,
            "direct": event.get("direct") or [],
            "matched": matched,
        }
    return {
        "ok": True,
        "query": payload.query,
        "detected": detected,
        "would_search": (event.get("direct") or [])[:3] if event else [],
    }


@router.get("/areas/occasions")
async def area_occasions(
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await occasion_store.list_occasions(session)
    return {
        "ok": True,
        "area": user["area"],
        "occasions": [occasion_store.to_dict(row) for row in rows],
    }


@router.post("/areas/occasions")
async def area_occasion_create(
    payload: OccasionPayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        row = await occasion_store.create_occasion(
            session,
            name=payload.name,
            aliases=payload.aliases,
            direct=payload.direct,
            exclude=payload.exclude,
            exclude_categories=payload.exclude_categories,
            bridges=payload.bridges,
            area=user["area"],
            status=payload.status,
            priority=payload.priority,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=user["username"],
        )
    except occasion_store.OccasionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.put("/areas/occasions/{occasion_id}")
async def area_occasion_update(
    occasion_id: str,
    payload: OccasionPayload,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None or row.area != user["area"]:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    try:
        row = await occasion_store.update_occasion(
            session,
            row,
            name=payload.name,
            aliases=payload.aliases,
            direct=payload.direct,
            exclude=payload.exclude,
            exclude_categories=payload.exclude_categories,
            bridges=payload.bridges,
            area=user["area"],
            status=payload.status,
            priority=payload.priority,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=user["username"],
        )
    except occasion_store.OccasionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.post("/areas/occasions/{occasion_id}/publish")
async def area_occasion_publish(
    occasion_id: str,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None or row.area != user["area"]:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    row = await occasion_store.publish_occasion(
        session, row, changed_by=user["username"]
    )
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.delete("/areas/occasions/{occasion_id}")
async def area_occasion_delete(
    occasion_id: str,
    user: dict = Depends(require_area_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None or row.area != user["area"]:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    await occasion_store.delete_occasion(session, row)
    return {"ok": True}


@router.get(
    "/admin/overview",
    dependencies=[Depends(require_center_admin)],
)
async def admin_overview(
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await overview_service.overview(session)


@router.get(
    "/admin/occasions",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasions(
    area: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = await occasion_store.list_occasions(
        session, area=area, status=status
    )
    return {
        "ok": True,
        "occasions": [occasion_store.to_dict(row) for row in rows],
    }


@router.post(
    "/admin/occasions/seed",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasions_seed(
    session: AsyncSession = Depends(get_session),
) -> dict:
    added = await occasion_store.seed_examples(session)
    return {"ok": True, "added": added}


@router.post(
    "/admin/occasions",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasion_create(
    payload: OccasionPayload,
    admin: dict = Depends(require_center_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        row = await occasion_store.create_occasion(
            session,
            name=payload.name,
            aliases=payload.aliases,
            direct=payload.direct,
            exclude=payload.exclude,
            exclude_categories=payload.exclude_categories,
            bridges=payload.bridges,
            area=payload.area,
            status=payload.status,
            priority=payload.priority,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=admin["username"],
        )
    except occasion_store.OccasionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.put(
    "/admin/occasions/{occasion_id}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasion_update(
    occasion_id: str,
    payload: OccasionPayload,
    admin: dict = Depends(require_center_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    try:
        row = await occasion_store.update_occasion(
            session,
            row,
            name=payload.name,
            aliases=payload.aliases,
            direct=payload.direct,
            exclude=payload.exclude,
            exclude_categories=payload.exclude_categories,
            bridges=payload.bridges,
            area=payload.area,
            status=payload.status,
            priority=payload.priority,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            changed_by=admin["username"],
        )
    except occasion_store.OccasionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.post(
    "/admin/occasions/{occasion_id}/publish",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasion_publish(
    occasion_id: str,
    admin: dict = Depends(require_center_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    row = await occasion_store.publish_occasion(
        session, row, changed_by=admin["username"]
    )
    return {"ok": True, "occasion": occasion_store.to_dict(row)}


@router.delete(
    "/admin/occasions/{occasion_id}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_occasion_delete(
    occasion_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await occasion_store.get_occasion(session, occasion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ocasión no encontrada")
    await occasion_store.delete_occasion(session, row)
    return {"ok": True}


@router.get(
    "/admin/area-rules",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_rules(
    area: str | None = None,
    status: str | None = None,
    rule_type: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rules = await area_rules.list_rules(
        session, area=area, status=status, rule_type=rule_type
    )
    return {"ok": True, "rules": [area_rules.to_dict(rule) for rule in rules]}


@router.post(
    "/admin/area-rules",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_rule_create(
    payload: AreaRulePayload,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        rule = await area_rules.create_rule(
            session,
            area=payload.area,
            name=payload.name,
            rule_type=payload.rule_type,
            condition=payload.condition,
            action=payload.action,
            priority=payload.priority,
            status=payload.status,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.put(
    "/admin/area-rules/{rule_id}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_rule_update(
    rule_id: str,
    payload: AreaRulePayload,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    try:
        rule = await area_rules.update_rule(
            session,
            rule,
            name=payload.name,
            rule_type=payload.rule_type,
            condition=payload.condition,
            action=payload.action,
            priority=payload.priority,
            status=payload.status,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
        )
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.post(
    "/admin/area-rules/{rule_id}/publish",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_rule_publish(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    try:
        rule = await area_rules.set_status(session, rule, "published")
    except area_rules.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "rule": area_rules.to_dict(rule)}


@router.delete(
    "/admin/area-rules/{rule_id}",
    dependencies=[Depends(require_center_admin)],
)
async def admin_area_rule_delete(
    rule_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    rule = await area_rules.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Regla no encontrada")
    await area_rules.delete_rule(session, rule)
    return {"ok": True}


@router.post(
    "/admin/knowledge/reload",
    dependencies=[Depends(require_admin)],
)
async def admin_knowledge_reload() -> dict:
    return {"ok": True, "articles": knowledge.reload()}


@router.post(
    "/internal/catalog/refresh",
    dependencies=[Depends(require_internal_refresh)],
)
async def admin_catalog_refresh(
    sku: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Refresca un SKU desde VTEX (precio, ficha y promoción)."""
    try:
        result = await refresh_service.refresh_item(session, sku)
    except SapError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    if not result.get("ok"):
        status = 409 if "SAP_MODE" in str(result.get("error")) else 404
        raise HTTPException(
            status_code=status,
            detail=result.get("error", "No se pudo refrescar el SKU"),
        )
    return result


@router.get(
    "/admin/knowledge",
    dependencies=[Depends(require_admin)],
)
async def admin_knowledge_list() -> dict:
    articles = knowledge.load_articles(force=True)
    return {
        "ok": True,
        "articles": [
            {
                "title": article.title,
                "status": article.status,
                "tags": article.tags,
                "source": article.source,
            }
            for article in articles
        ],
    }


@router.post(
    "/admin/orders/{order_number}/delivered",
    dependencies=[Depends(require_admin)],
)
async def admin_mark_delivered(
    order_number: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await feedback_service.mark_delivered(session, order_number)


@router.get(
    "/admin/webhook/status",
    dependencies=[Depends(require_admin)],
)
async def webhook_status(
    session: AsyncSession = Depends(get_session),
) -> dict:
    last_inbound = await session.scalar(
        select(Message.created_at)
        .where(Message.direction == "in")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_outbound = await session.scalar(
        select(Message.created_at)
        .where(Message.direction == "out")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_event = await session.scalar(
        select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(1)
    )
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    event_counts = (
        await session.execute(
            select(WebhookEvent.status, func.count(WebhookEvent.id))
            .where(WebhookEvent.received_at >= since)
            .group_by(WebhookEvent.status)
        )
    ).all()
    paused = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.bot_paused.is_(True))
    )
    pending_handoffs = await session.scalar(
        select(func.count())
        .select_from(Handoff)
        .where(Handoff.status.in_(("pending", "taken")))
    )
    now = datetime.now(timezone.utc)

    def minutes(value):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int((now - value).total_seconds() // 60)

    return {
        "public_base_url": settings.public_base_url,
        "webhook_path": "/webhooks/whatsapp",
        "last_inbound_at": last_inbound.isoformat()
        if last_inbound
        else None,
        "minutes_since_last_inbound": minutes(last_inbound),
        "last_outbound_at": last_outbound.isoformat()
        if last_outbound
        else None,
        "last_event": {
            "at": last_event.received_at.isoformat()
            if last_event and last_event.received_at
            else None,
            "status": last_event.status if last_event else None,
            "messages": last_event.message_count if last_event else 0,
            "error": last_event.error if last_event else None,
        },
        "events_24h": {status: int(count) for status, count in event_counts},
        "paused_conversations": int(paused or 0),
        "pending_handoffs": int(pending_handoffs or 0),
    }


@router.get(
    "/admin/commerce/status",
    dependencies=[Depends(require_admin)],
)
async def commerce_status() -> dict:
    return {
        "native_catalog_enabled": settings.wa_native_catalog_enabled,
        "native_cart_enabled": settings.wa_native_cart_enabled,
        "catalog_id": settings.wa_catalog_id,
        "commerce_account_id": settings.wa_commerce_account_id,
        "phone_number_id": settings.wa_phone_number_id,
        "waba_id": settings.wa_waba_id,
        "ready": native_commerce.is_ready(),
        "cart_ready": native_commerce.cart_ready(),
        **native_commerce.cart_status(),
    }


# ---------------------------------------------------------------------------
# WhatsApp webhook
# ---------------------------------------------------------------------------


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(request: Request) -> str:
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        return params.get("hub.challenge", "")
    raise HTTPException(status_code=403, detail="Verificación inválida")


def _iter_messages(payload: dict):
    expected = (settings.wa_phone_number_id or "").strip()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # Durante una migración pueden convivir dos números en la misma app:
            # se procesan solo los mensajes del número configurado, para no
            # contestar desde el número equivocado.
            phone_number_id = str(
                (value.get("metadata") or {}).get("phone_number_id") or ""
            ).strip()
            if expected and phone_number_id and phone_number_id != expected:
                logger.info(
                    "Webhook de otro número (%s); se ignora", phone_number_id
                )
                continue
            contacts = value.get("contacts") or []
            name = None
            if contacts:
                name = (contacts[0].get("profile") or {}).get("name")
            for message in value.get("messages", []):
                order = extract_order(message)
                if order is not None:
                    yield {
                        "wa_id": message.get("from", ""),
                        "text": "",
                        "wa_message_id": message.get("id", ""),
                        "name": name,
                        "order": order,
                    }
                    continue
                text = extract_text(message).strip()
                if not text:
                    logger.info("Mensaje sin texto ignorado: %s", message.get("type"))
                    continue
                media = None
                kind = message.get("type")
                if kind in {"image", "video", "document", "audio"}:
                    content = message.get(kind) or {}
                    media = {
                        "media_id": content.get("id"),
                        "mime_type": content.get("mime_type"),
                        "filename": content.get("filename"),
                        "kind": kind,
                    }
                yield {
                    "wa_id": message.get("from", ""),
                    "text": text,
                    "wa_message_id": message.get("id", ""),
                    "name": name,
                    "media": media,
                }


@router.post("/webhooks/whatsapp")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default="", alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_session),
):
    raw = await request.body()
    webhook_event = WebhookEvent(status="received")
    session.add(webhook_event)
    await session.commit()
    if not verify_signature(raw, x_hub_signature_256):
        webhook_event.status = "invalid_signature"
        webhook_event.error = "Firma inválida"
        await session.commit()
        raise HTTPException(status_code=403, detail="Firma inválida")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        webhook_event.status = "invalid_json"
        webhook_event.error = str(exc)[:300]
        await session.commit()
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    processed = 0
    for item in _iter_messages(payload):
        processed += 1
        try:
            if settings.queue_enabled:
                try:
                    pool = await _redis()
                    await pool.enqueue_job("process_inbound", **item)
                except Exception:  # noqa: BLE001 - si Redis cae, no perder el mensaje
                    logger.exception("No se pudo encolar; se procesa inline")
                    await ingest_inbound(session, **item)
            else:
                await ingest_inbound(session, **item)
        except Exception:  # noqa: BLE001 - Meta reintenta; no tumbar el webhook
            logger.exception("Error procesando mensaje %s", item.get("wa_message_id"))
            webhook_event.status = "error"
            webhook_event.error = (
                f"No se pudo procesar {item.get('wa_message_id')}"
            )[:300]
    webhook_event.message_count = processed
    if webhook_event.status == "received":
        webhook_event.status = "ok"
    await session.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Pago simulado por QR (reemplazar por la pasarela real)
# ---------------------------------------------------------------------------


_PAGE_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;
color:#1f2937;margin:0;padding:24px}
.card{max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:24px;
box-shadow:0 8px 30px rgba(0,0,0,.08)}
h1{font-size:20px;margin:0 0 4px}
.muted{color:#6b7280;font-size:13px}
.total{font-size:22px;font-weight:700;margin:16px 0}
ul{padding-left:18px;line-height:1.6}
button{width:100%;padding:14px;border:0;border-radius:10px;background:#16a34a;color:#fff;
font-size:16px;font-weight:600;cursor:pointer}
.ok{background:#dcfce7;color:#166534;padding:12px;border-radius:10px}
.err{background:#fee2e2;color:#991b1b;padding:12px;border-radius:10px}
.qr{display:block;margin:16px auto;border:8px solid #fff;border-radius:8px}
code{background:#f3f4f6;padding:2px 6px;border-radius:6px;font-size:12px}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_PAGE_CSS}</style></head>
<body><div class="card">{body}</div></body></html>"""
    )


async def _load_payment(session: AsyncSession, payment_id: str) -> tuple[Payment, Order]:
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    order = await session.scalar(
        select(Order).options(selectinload(Order.items)).where(Order.id == payment.order_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return payment, order


@router.get("/mock/pay/{payment_id}", response_class=HTMLResponse)
async def mock_pay_page(payment_id: str, session: AsyncSession = Depends(get_session)):
    payment, order = await _load_payment(session, payment_id)
    raw = payment.raw or {}
    items = "".join(
        f"<li>{html.escape(item.name)} × {item.quantity} — "
        f"Bs {Decimal(item.line_total):,.2f}</li>"
        for item in order.items
    )
    if payment.status == "paid":
        body = f"""
        <h1>Pago confirmado</h1>
        <p class="muted">Pedido {html.escape(order.number)}</p>
        <p class="total">Bs {Decimal(payment.amount):,.2f}</p>
        <p class="ok">Factura SAP: {payment.invoice_doc_entry or order.invoice_doc_entry}</p>
        <ul>{items}</ul>
        <p class="muted">Pago confirmado por la pasarela. La factura quedó relacionada
        con el cobro en SAP.</p>
        """
    elif raw.get("qrImageUrl") or raw.get("qrImageBase64"):
        qr_url = raw.get("qrImageUrl")
        qr_src = qr_url or (
            "data:image/png;base64," + str(raw.get("qrImageBase64"))
        )
        body = f"""
        <h1>Pagar pedido</h1>
        <p class="muted">Pedido {html.escape(order.number)} · ref
        <code>{html.escape(payment.provider_ref or payment.id)}</code></p>
        <p class="total">Bs {Decimal(payment.amount):,.2f}</p>
        <ul>{items}</ul>
        <img class="qr" src="{html.escape(qr_src)}" width="260" height="260"
             alt="QR de pago">
        <p class="ok">Escanea el QR desde la app de tu banco. La confirmación llega
        automáticamente por webhook.</p>
        <p class="muted">Proveedor: {html.escape(payment.provider)}. No cierres esta
        página hasta completar el pago.</p>
        """
    else:
        body = f"""
        <h1>Pagar pedido</h1>
        <p class="muted">Pedido {html.escape(order.number)} · ref
        <code>{html.escape(payment.provider_ref or payment.id)}</code></p>
        <p class="total">Bs {Decimal(payment.amount):,.2f}</p>
        <ul>{items}</ul>
        <img class="qr" src="/mock/pay/{payment.id}/qr.png" width="240" height="240"
             alt="QR de pago simulado">
        <form method="post" action="/mock/pay/{payment.id}/confirm">
          <button type="submit">Confirmar pago (simulado)</button>
        </form>
        <p class="muted">Esto simula la confirmación de la pasarela: marca el pago,
        genera la factura en SAP y la relaciona con el cobro.</p>
        """
    return _page("Pago QR", body)


@router.get("/mock/pay/{payment_id}/qr.png")
async def mock_qr(payment_id: str, session: AsyncSession = Depends(get_session)):
    payment, _ = await _load_payment(session, payment_id)
    image = qrcode.make(payment.qr_payload or payment.id)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.post("/mock/pay/{payment_id}/confirm")
async def mock_confirm(payment_id: str, session: AsyncSession = Depends(get_session)):
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    if payment.provider != "mock_qr":
        raise HTTPException(
            status_code=400,
            detail="Este pago se confirma en la pasarela real, no en el mock.",
        )
    try:
        await confirm_payment(session, payment_id, get_sap(session), whatsapp)
    except (CheckoutError, SapError) as exc:
        return _page(
            "Error de pago",
            f'<h1>No se pudo confirmar</h1><p class="err">{html.escape(str(exc))}</p>',
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error confirmando pago %s", payment_id)
        return _page(
            "Error de pago",
            f'<h1>Error inesperado</h1><p class="err">{html.escape(str(exc))}</p>',
        )
    return RedirectResponse(url=f"/mock/pay/{payment_id}", status_code=303)


@router.post("/webhooks/payments/cucu")
async def cucu_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    raw = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not verify_standard_webhook(
        headers, raw, settings.cucu_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    if payload.get("event") != "qr.paid":
        return {"status": "ignored", "event": payload.get("event")}

    data = payload.get("data") or {}
    qr_id = str(data.get("qrId") or "")
    payment = await session.scalar(
        select(Payment).where(
            Payment.provider_ref == qr_id, Payment.provider == "cucu_qr"
        )
    )
    if payment is None and data.get("externalReference"):
        order = await session.scalar(
            select(Order).where(Order.number == data["externalReference"])
        )
        if order is not None:
            payment = await session.scalar(
                select(Payment).where(Payment.order_id == order.id)
            )
    if payment is None:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    event_id = headers.get("webhook-id") or f"cucu-{qr_id}"
    duplicate = await session.scalar(
        select(PaymentEvent.id).where(PaymentEvent.provider_event_id == event_id)
    )
    if duplicate:
        return {"status": "duplicate"}

    try:
        paid_amount = Decimal(str(data.get("amount", payment.amount)))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Monto inválido") from exc
    if paid_amount != Decimal(payment.amount):
        logger.error(
            "Webhook CUCU con monto distinto: %s != %s", paid_amount, payment.amount
        )
        raise HTTPException(status_code=400, detail="El monto no coincide")

    session.add(
        PaymentEvent(
            payment_id=payment.id,
            provider_event_id=event_id,
            payload=payload,
        )
    )
    await confirm_payment(session, payment.id, get_sap(session), whatsapp)
    # confirm_payment ya hace commit cuando cobra; este commit cubre el caso
    # idempotente (pago ya confirmado) para no perder el evento.
    await session.commit()
    return {"status": "ok"}


@router.post("/webhooks/payments/{provider}")
async def payment_webhook(provider: str):
    raise HTTPException(
        status_code=501,
        detail=(
            f"Webhook de '{provider}' pendiente. Implementar verificación de firma, "
            "idempotencia y llamada a confirm_payment()."
        ),
    )


# ---------------------------------------------------------------------------
# Demo sin Meta
# ---------------------------------------------------------------------------


class SimulateIn(BaseModel):
    wa_id: str
    text: str
    name: str | None = None
    deliver: bool = False


@router.post("/dev/simulate")
async def simulate(
    payload: SimulateIn,
    session: AsyncSession = Depends(get_session),
):
    if settings.app_env == "production":
        raise HTTPException(status_code=404)
    wa_id = "".join(ch for ch in payload.wa_id if ch.isdigit())
    replies = await ingest_inbound(
        session,
        wa_id=wa_id,
        text=payload.text,
        wa_message_id=f"dev-{uuid.uuid4()}",
        name=payload.name,
        deliver=payload.deliver,
    )
    return {"wa_id": wa_id, "replies": replies}


# ---------------------------------------------------------------------------
# Panel / API de administración
# ---------------------------------------------------------------------------


class ReplyIn(BaseModel):
    text: str


class ResolveIn(BaseModel):
    text: str
    category: str


class TransferIn(BaseModel):
    to: str


class ReturnIn(BaseModel):
    reason: str = "El asesor devolvió el caso al bot."


class SurveyIn(BaseModel):
    rating: int
    comment: str = ""


@router.get("/admin/handoffs/view", response_class=HTMLResponse)
async def admin_handoffs_view() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Handoffs · ROHO</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f5f6f8;color:#1f2937}
  header{background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;padding:16px 22px;display:flex;justify-content:space-between;align-items:center;gap:14px;flex-wrap:wrap}
  h1{font-size:18px;margin:0}
  .nav{display:flex;gap:14px;align-items:center;font-size:14px}
  .nav a{color:#cbd5e1;text-decoration:none}
  .bell{background:#1e293b;border:1px solid #334155;color:#fff;border-radius:999px;padding:7px 11px;cursor:pointer}
  .bell .count{background:#ef4444;color:#fff;border-radius:999px;padding:1px 6px;font-size:11px;margin-left:6px}
  .duty{font-size:12px;color:#cbd5e1}
  #toasts{position:fixed;right:18px;top:70px;z-index:50;display:flex;flex-direction:column;gap:8px;max-width:320px}
  .toast{background:#111827;color:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 8px 24px #0003;font-size:13px}
  .empty{text-align:center;color:#6b7280;padding:42px;background:#fff;border:1px dashed #d1d5db;border-radius:12px}
  .context{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:12px 0}
  .context .box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px;font-size:13px}
  .context h4{margin:0 0 6px;font-size:12px;text-transform:uppercase;color:#6b7280}
  main{max-width:980px;margin:22px auto;padding:0 16px}
  .card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 2px #0001}
  .row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .muted{color:#6b7280;font-size:13px}
  .status{font-size:12px;font-weight:700;padding:3px 8px;border-radius:999px;background:#fef3c7;color:#92400e}
  .status.taken{background:#dbeafe;color:#1e40af}.status.resolved{background:#dcfce7;color:#166534}
  .status.overdue{background:#fee2e2;color:#991b1b}
  .context{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:12px 0}
  .context .box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:10px;font-size:13px}
  .context h4{margin:0 0 6px;font-size:12px;text-transform:uppercase;color:#6b7280}
  button{border:0;border-radius:8px;padding:8px 12px;font-weight:600;cursor:pointer;background:#111827;color:#fff;margin:4px 4px 0 0}
  button.secondary{background:#e5e7eb;color:#111827}
  pre{white-space:pre-wrap;background:#f9fafb;padding:10px;border-radius:8px;font-size:13px}
  #detail{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin-top:18px}
</style>
</head>
<body>
<header>
  <div><h1>Bandeja de asesores</h1><div class="duty" id="duty">Guardia: —</div></div>
  <nav class="nav">
    <a href="/admin/handoffs/view">Bandeja</a>
    <a id="agentsLink" href="/admin/advisors/view" style="display:none">Agentes</a>
    <button class="bell" id="bell" title="Activar notificaciones">🔔<span class="count" id="badge">0</span></button>
    <span id="who"></span>
  </nav>
</header>
<div id="toasts"></div>
<main>
  <p class="muted">Handoffs pendientes y tomados. Refrescá para actualizar.</p>
  <div id="list">Cargando…</div>
  <div id="detail" hidden></div>
</main>
<script>
let advisor = null;
let knownHandoffs = null;

async function api(path, opts={}) {
  const headers = Object.assign({}, opts.headers || {}, {
    'Content-Type': 'application/json'
  });
  const r = await fetch(path, Object.assign({}, opts, {headers, credentials:'same-origin'}));
  if (r.status === 401) { window.location.href = '/advisor/login'; throw new Error('Sesión vencida'); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function toast(text) {
  const box = document.getElementById('toasts');
  const div = document.createElement('div');
  div.className = 'toast';
  div.textContent = text;
  box.appendChild(div);
  setTimeout(() => div.remove(), 6000);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('Nuevo handoff', {body: text});
  }
}

async function boot() {
  advisor = await api('/advisor/me');
  document.getElementById('who').innerHTML =
    `${esc(advisor.display_name)} · <a style="color:#9ca3af" href="/advisor/logout">Salir</a>`;
  if (advisor.is_admin) document.getElementById('agentsLink').style.display = 'inline';
  const duty = await api('/advisor/duty');
  document.getElementById('duty').textContent = duty.on_duty.length
    ? 'Guardia: ' + duty.on_duty.map(a => a.display_name).join(', ')
    : 'Guardia: sin asesor asignado';
  document.getElementById('bell').addEventListener('click', async () => {
    if ('Notification' in window && Notification.permission === 'default') {
      await Notification.requestPermission();
    }
    toast('Notificaciones del navegador: ' + (('Notification' in window) ? Notification.permission : 'no disponibles'));
  });
  await load();
  setInterval(load, 10000);
}
function esc(s){return String(s??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

async function load() {
  const box = document.getElementById('list');
  try {
    const data = await api('/admin/handoffs');
    const currentIds = new Set(data.handoffs.map(h => h.id));
    if (knownHandoffs === null) {
      knownHandoffs = currentIds;
    } else {
      for (const h of data.handoffs) {
        if (!knownHandoffs.has(h.id) && h.status === 'pending') {
          toast(`${h.contact} pidió un asesor · ${h.reason || ''}`);
        }
      }
      knownHandoffs = currentIds;
    }
    document.getElementById('badge').textContent = data.handoffs.length;
    if (!data.handoffs.length) {
      box.innerHTML = '<div class="empty">No hay handoffs abiertos 🎉</div>';
      return;
    }
    box.innerHTML = data.handoffs.map(h => `
      <div class="card">
        <div class="row">
          <div>
            <strong>${esc(h.contact)}</strong>
            <div class="muted">${esc(h.wa_id)} · ${esc(h.reason || 'sin motivo')}</div>
            <div class="muted">Esperando ${h.waiting_minutes} min · ${h.assigned_to ? 'Asignado a '+esc(h.assigned_to) : 'Sin asignar'} ${h.overdue ? '· ⚠ SLA vencido' : ''}</div>
          </div>
          <div><span class="status ${esc(h.status)} ${h.overdue ? 'overdue' : ''}">${esc(h.status)}</span></div>
        </div>
        <button onclick="take('${h.id}')">Tomar</button>
        <button class="secondary" onclick="detail('${h.id}')">Ver conversación</button>
        <button class="secondary" onclick="reply('${h.id}')">Responder</button>
        <button class="secondary" onclick="resolve('${h.id}')">Resolver</button>
      </div>`).join('');
  } catch (e) { box.textContent = 'Error: ' + e.message; }
}

async function take(id) {
  await api('/admin/handoffs/' + id + '/take', {method:'POST'});
  load();
}
async function resolve(id) {
  const notes = prompt('Nota de resolución (opcional)', '');
  await api('/admin/handoffs/' + id + '/resolve', {method:'POST', body: JSON.stringify({text: notes || ''})});
  load();
}
async function reply(id) {
  const text = prompt('Mensaje para el cliente');
  if (!text) return;
  const r = await api('/admin/handoffs/' + id + '/reply', {method:'POST', body: JSON.stringify({text})});
  alert(r.ok ? 'Mensaje enviado' : 'No se pudo enviar');
}
async function detail(id) {
  const data = await api('/admin/handoffs/' + id);
  const h = data.handoff;
  const msgs = h.messages.map(m => `[${esc(m.direction)}] ${esc(m.text || m.type)}`).join('\\n');
  const orders = (h.orders || []).map(o => `#${esc(o.number)} · ${esc(o.status)} · Bs ${esc(o.total)}`).join('\\n') || 'Sin pedidos';
  const cart = h.cart ? `${h.cart.count} ítems · Bs ${h.cart.total}` : 'Carrito vacío';
  const events = (h.events || []).map(e => `[${esc(e.created_at)}] ${esc(e.advisor || 'sistema')} · ${esc(e.action)}`).join('\\n') || 'Sin eventos';
  const box = document.getElementById('detail');
  box.hidden = false;
  box.innerHTML = `<h3>${esc(h.contact.name || h.contact.wa_id)}</h3>
    <p class="muted">${esc(h.contact.phone)} · ${esc(h.reason || '')} · Esperando ${h.waiting_minutes} min ${h.overdue ? '· SLA vencido' : ''}</p>
    <div class="context">
      <div class="box"><h4>Cliente</h4>${esc(h.profile?.city || 'Sin ciudad')}<br>${esc(h.profile?.preferred_store || 'Sin tienda preferida')}</div>
      <div class="box"><h4>Carrito</h4>${esc(cart)}</div>
      <div class="box"><h4>Pedidos</h4><pre style="margin:0;padding:0;background:none">${esc(orders)}</pre></div>
    </div>
    <h4>Conversación</h4>
    <pre>${esc(msgs)}</pre>
    <h4>Auditoría</h4>
    <pre>${esc(events)}</pre>
    <button class="secondary" onclick="document.getElementById('detail').hidden=true">Cerrar</button>`;
}
boot();
</script>
</body>
</html>"""
    )


@router.get(
    "/admin/handoffs",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoffs(
    status: str = "open",
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await handoffs.reassign_stale_handoffs(
        session, settings.handoff_reassign_minutes
    )
    return {
        "ok": True,
        "handoffs": await handoffs.list_handoffs(
            session,
            status=status,
            advisor=advisor["username"],
            advisor_name=advisor["display_name"],
            view_all=bool(advisor.get("is_supervisor")),
        ),
    }


@router.get(
    "/admin/handoffs/{handoff_id}",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_detail(
    handoff_id: str,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await handoffs.get_handoff(
        session,
        handoff_id,
        advisor=advisor["username"],
        advisor_name=advisor["display_name"],
        is_admin=bool(advisor.get("is_admin")),
        is_supervisor=bool(advisor.get("is_supervisor")),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    return {"ok": True, "handoff": result}


@router.get(
    "/admin/handoffs/{handoff_id}/messages/{message_id}/media",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_media(
    handoff_id: str,
    message_id: str,
    session: AsyncSession = Depends(get_session),
):
    handoff = await session.get(Handoff, handoff_id)
    message = await session.get(Message, message_id)
    if handoff is None or message is None or message.conversation_id != handoff.conversation_id:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    media = (message.payload or {}).get("media") or {}
    media_id = media.get("media_id")
    if not media_id:
        raise HTTPException(status_code=404, detail="El mensaje no tiene archivo")
    try:
        content, content_type = await whatsapp.download_media(media_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo descargar el archivo: {str(exc)[:200]}",
        ) from exc
    filename = (media.get("filename") or f"{message_id}").replace('"', "")
    disposition = "inline" if content_type.startswith("image/") else "attachment"
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post(
    "/admin/handoffs/{handoff_id}/notes",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_note(
    handoff_id: str,
    payload: ReplyIn,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await handoffs.add_note(
        session, handoff_id, advisor["username"], payload.text
    )


@router.post(
    "/admin/handoffs/{handoff_id}/attachment",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_attachment(
    handoff_id: str,
    file: UploadFile = File(...),
    caption: str = Form(default=""),
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
):
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if handoff.status != "taken":
        raise HTTPException(
            status_code=409,
            detail="Primero tomá el caso para poder enviar archivos.",
        )
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(
            status_code=403,
            detail=f"El caso está asignado a {handoff.assigned_to}.",
        )
    conversation = await session.get(Conversation, handoff.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    contact = await session.get(Contact, conversation.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    if len(data) > 16 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El archivo supera 16 MB")
    mime = file.content_type or "application/octet-stream"
    try:
        message_id = await whatsapp.send_media(
            contact.wa_id,
            data,
            file.filename or "archivo",
            mime,
            caption[:1024],
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo enviar el archivo por WhatsApp. "
                f"{str(exc)[:200]}"
            ),
        ) from exc
    kind = "image" if mime.startswith("image/") else "document"
    session.add(
        Message(
            conversation_id=conversation.id,
            wa_message_id=message_id,
            direction="out",
            type=kind,
            text=caption[:1024] or file.filename,
            payload={"filename": file.filename, "mime_type": mime},
        )
    )
    await handoffs._event(
        session,
        handoff_id,
        "attachment",
        advisor=advisor["username"],
        detail=file.filename,
    )
    await session.commit()
    return {"ok": True, "message_id": message_id, "type": kind}


@router.post(
    "/admin/handoffs/{handoff_id}/take",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_take(
    handoff_id: str,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await handoffs.take_handoff(
        session,
        handoff_id,
        advisor["display_name"],
        advisor=advisor["username"],
        is_admin=bool(
            advisor.get("is_admin") or advisor.get("is_supervisor")
        ),
        whatsapp=whatsapp,
    )
    if not result.get("ok"):
        detail = {
            "handoff_not_found": "Handoff no encontrado",
            "already_taken": "Otro asesor ya tomó este caso",
            "already_resolved": "El caso ya fue resuelto",
        }.get(result.get("reason"), "No se pudo tomar el caso")
        raise HTTPException(status_code=409, detail=detail)
    handoff = await session.get(Handoff, handoff_id)
    if handoff is not None:
        conversation = await session.get(Conversation, handoff.conversation_id)
        contact = (
            await session.get(Contact, conversation.contact_id)
            if conversation is not None
            else None
        )
        if contact is not None:
            try:
                await whatsapp.send_text(
                    contact.wa_id,
                    (
                        f"Tu caso fue asignado a {advisor['display_name']}. "
                        "Te va a responder por acá."
                    ),
                )
            except Exception:  # noqa: BLE001 - no tumbar la asignación
                logger.exception("No se pudo avisar al cliente de la asignación")
    return result


@router.post(
    "/admin/handoffs/{handoff_id}/resolve",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_resolve(
    handoff_id: str,
    payload: ResolveIn,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if handoff.status != "taken":
        raise HTTPException(
            status_code=409,
            detail="Primero tomá el caso para poder resolverlo.",
        )
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(
            status_code=403,
            detail=f"El caso está asignado a {handoff.assigned_to}.",
        )
    solution = (payload.text if payload else "").strip()
    if not solution:
        raise HTTPException(
            status_code=400,
            detail="Indicá la solución aplicada antes de resolver.",
        )
    if payload.category not in handoffs.RESOLUTION_CATEGORIES:
        raise HTTPException(status_code=400, detail="Categoría inválida")
    result = await handoffs.resolve_handoff(
        session,
        handoff_id,
        notes=solution,
        category=payload.category,
        advisor=advisor["username"],
        whatsapp=whatsapp,
    )
    if result.get("ok"):
        handoff = await session.get(Handoff, handoff_id)
        conversation = (
            await session.get(Conversation, handoff.conversation_id)
            if handoff is not None
            else None
        )
        contact = (
            await session.get(Contact, conversation.contact_id)
            if conversation is not None
            else None
        )
        if handoff is not None and contact is not None:
            survey = await handoffs.create_survey(session, handoff, contact)
            try:
                await whatsapp.send_list(
                    contact.wa_id,
                    (
                        "¿Cómo calificás la atención? "
                        "Tu opinión nos ayuda a mejorar."
                    ),
                    [
                        {
                            "title": "Calificá la atención",
                            "rows": [
                                {"id": f"survey:{survey.token}:5", "title": "5 · Excelente"},
                                {"id": f"survey:{survey.token}:4", "title": "4 · Muy buena"},
                                {"id": f"survey:{survey.token}:3", "title": "3 · Regular"},
                                {"id": f"survey:{survey.token}:2", "title": "2 · Mala"},
                                {"id": f"survey:{survey.token}:1", "title": "1 · Muy mala"},
                            ],
                        }
                    ],
                    button_text="Calificar",
                )
            except Exception:  # noqa: BLE001
                logger.exception("No se pudo enviar la encuesta")
    return result


@router.post(
    "/admin/handoffs/{handoff_id}/transfer",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_transfer(
    handoff_id: str,
    payload: TransferIn,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if handoff.status != "taken":
        raise HTTPException(status_code=409, detail="El caso no está tomado")
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(status_code=403, detail="El caso es de otro asesor")
    target = await session.scalar(
        select(Advisor).where(
            Advisor.active.is_(True),
            (Advisor.display_name == payload.to)
            | (Advisor.username == payload.to),
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Asesor destino no encontrado")
    return await handoffs.transfer_handoff(
        session, handoff_id, target.display_name, advisor["username"]
    )


@router.post(
    "/admin/handoffs/{handoff_id}/return-to-bot",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_return(
    handoff_id: str,
    payload: ReturnIn,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if handoff.status != "taken":
        raise HTTPException(status_code=409, detail="El caso no está tomado")
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(status_code=403, detail="El caso es de otro asesor")
    return await handoffs.return_to_bot(
        session, handoff_id, payload.reason, advisor["username"]
    )


@router.post(
    "/admin/handoffs/{handoff_id}/reopen",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_reopen(
    handoff_id: str,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(status_code=403, detail="El caso es de otro asesor")
    return await handoffs.reopen_handoff(
        session,
        handoff_id,
        advisor=advisor["username"],
        advisor_name=advisor["display_name"],
    )


@router.post(
    "/admin/handoffs/{handoff_id}/reply",
    dependencies=[Depends(require_advisor)],
)
async def admin_handoff_reply(
    handoff_id: str,
    payload: ReplyIn,
    advisor: dict = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> dict:
    handoff = await session.get(Handoff, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff no encontrado")
    if handoff.status != "taken":
        raise HTTPException(
            status_code=409,
            detail="Primero tomá el caso para poder responder.",
        )
    if (
        handoff.assigned_to
        and handoff.assigned_to != advisor["display_name"]
        and not advisor.get("is_supervisor")
    ):
        raise HTTPException(
            status_code=403,
            detail=f"El caso está asignado a {handoff.assigned_to}.",
        )
    result = await handoffs.reply_handoff(
        session, handoff_id, payload.text, whatsapp, advisor=advisor["username"]
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo enviar por WhatsApp. "
                "Verificá que el número esté permitido y dentro de la ventana de 24 h."
            ),
        )
    return result


@router.get("/api/conversations", dependencies=[Depends(require_admin)])
async def list_conversations(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(Conversation, Contact)
            .join(Contact, Contact.id == Conversation.contact_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": conversation.id,
            "contact": {
                "wa_id": contact.wa_id,
                "name": contact.name,
                "phone": contact.phone_e164,
            },
            "bot_paused": conversation.bot_paused,
            "last_message_at": conversation.last_message_at,
        }
        for conversation, contact in rows
    ]


@router.get(
    "/api/conversations/{conversation_id}/messages",
    dependencies=[Depends(require_admin)],
)
async def list_messages(
    conversation_id: str, session: AsyncSession = Depends(get_session)
):
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(200)
        )
    ).all()
    return [
        {
            "direction": row.direction,
            "type": row.type,
            "text": row.text,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post(
    "/api/conversations/{conversation_id}/reply",
    dependencies=[Depends(require_admin)],
)
async def agent_reply(
    conversation_id: str,
    payload: ReplyIn,
    session: AsyncSession = Depends(get_session),
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    contact = await session.get(Contact, conversation.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    message_id = await whatsapp.send_text(contact.wa_id, payload.text)
    session.add(
        Message(
            conversation_id=conversation.id,
            wa_message_id=message_id,
            direction="out",
            text=payload.text,
            payload={"human": True},
        )
    )
    conversation.bot_paused = True
    await session.commit()
    return {"status": "sent", "message_id": message_id}


@router.post(
    "/api/conversations/{conversation_id}/resume",
    dependencies=[Depends(require_admin)],
)
async def resume_bot(
    conversation_id: str, session: AsyncSession = Depends(get_session)
):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    conversation.bot_paused = False
    await session.commit()
    return {"status": "resumed"}


@router.get("/api/orders", dependencies=[Depends(require_admin)])
async def list_orders(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.scalars(
            select(Order).order_by(Order.created_at.desc()).limit(50)
        )
    ).all()
    return [
        {
            "number": order.number,
            "status": order.status,
            "total": str(order.total),
            "currency": order.currency,
            "sap_doc_entry": order.sap_doc_entry,
            "invoice_doc_entry": order.invoice_doc_entry,
            "created_at": order.created_at,
        }
        for order in rows
    ]


@router.get("/api/catalog", dependencies=[Depends(require_admin)])
async def list_catalog(
    q: str = "", limit: int = 20, session: AsyncSession = Depends(get_session)
):
    rows = await catalog.search_items(session, q, limit=min(limit, 50))
    return [
        {
            "sku": row.sku,
            "name": row.name,
            "price": str(row.price),
            "stock": row.stock,
            "category": row.category,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@router.get("/")
async def root():
    return {
        "service": "chatbot-whatsapp-sapb1",
        "version": __version__,
        "docs": "/docs",
        "webhook": "/webhooks/whatsapp",
        "demo": "/dev/simulate",
    }
