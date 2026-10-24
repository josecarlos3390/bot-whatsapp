"""Estado operativo consolidado para el tablero de administración."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from . import funnel, metrics, qa
from ..models import (
    AreaRule,
    AreaUser,
    Contact,
    Conversation,
    ConversationFlow,
    ConversationGuard,
    ConversationRecommendation,
    Handoff,
    Message,
    Occasion,
)

ROOT = Path(__file__).resolve().parent.parent.parent
LOGS = ROOT / "logs"


def _latest_sync() -> dict:
    files = sorted(
        LOGS.glob("vtex_sync_*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {"at": None, "failed": None, "file": None, "summary": ""}
    path = files[0]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    text = text.replace("\x00", "")
    lowered = text.lower()
    failed = "traceback" in lowered or "operationalerror" in lowered
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean = [
        line
        for line in lines
        if not line.startswith(("At ", "+ ", "python.exe :"))
        and "CategoryInfo" not in line
        and "FullyQualifiedErrorId" not in line
        and "RemoteException" not in line
    ]
    summary = " | ".join(clean[-3:])[-500:]
    return {
        "at": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "failed": failed,
        "file": path.name,
        "summary": summary,
    }


def _sync_status_file() -> dict:
    path = LOGS / "vtex_sync_status.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _scheduled_task() -> dict:
    try:
        executable = shutil.which("schtasks") or r"C:\Windows\System32\schtasks.exe"
        result = subprocess.run(
            [
                executable,
                "/query",
                "/tn",
                "Chatbot VTEX Sync",
                "/fo",
                "LIST",
                "/v",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(
            r"(?:Last Result|Último resultado|Resultado)\s*:\s*(\d+)",
            output,
            re.IGNORECASE,
        )
        next_match = re.search(
            r"(?:Next Run Time|Próxima ejecución|Hora de la próxima ejecución)"
            r"\s*:\s*(.+)",
            output,
            re.IGNORECASE,
        )
        return {
            "available": result.returncode == 0,
            "last_result": int(match.group(1)) if match else None,
            "next_run": next_match.group(1).strip()
            if next_match
            else None,
        }
    except Exception:  # noqa: BLE001 - el tablero no debe fallar por schtasks
        return {"available": False, "last_result": None, "next_run": None}


def _tool_stats() -> dict:
    path = LOGS / "bot_tools.jsonl"
    if not path.exists():
        return {"calls": 0, "failures": 0}
    calls = 0
    failures = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            calls += 1
            if row.get("ok") is False:
                failures += 1
    except OSError:
        pass
    return {"calls": calls, "failures": failures}


async def _api_health() -> dict:
    url = (settings.sap_paas_url or "").rstrip("/")
    if not url:
        return {"ok": False, "detail": "SAP_PAAS_URL no configurado"}
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(f"{url}/health/live")
        return {
            "ok": response.status_code < 400,
            "status": response.status_code,
            "detail": (response.text or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)[:200]}


async def _count(session: AsyncSession, model) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def overview(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    api = await _api_health()
    sync = _latest_sync()
    status_file = _sync_status_file()
    task = await asyncio.to_thread(_scheduled_task)
    if status_file:
        task = {
            "available": True,
            "last_result": status_file.get("exit_code"),
            "next_run": task.get("next_run"),
            "source": "status_file",
            "steps": status_file.get("steps") or [],
        }
        if status_file.get("last_run"):
            sync["at"] = status_file["last_run"]
        if status_file.get("exit_code") not in (0, None):
            sync["failed"] = True
    tools = await asyncio.to_thread(_tool_stats)

    counts = {
        "contacts": await _count(session, Contact),
        "conversations": await _count(session, Conversation),
        "messages_24h": int(
            await session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.created_at >= since)
            )
            or 0
        ),
        "handoffs_open": int(
            await session.scalar(
                select(func.count())
                .select_from(Handoff)
                .where(Handoff.status.in_(("pending", "taken")))
            )
            or 0
        ),
        "rules_published": int(
            await session.scalar(
                select(func.count())
                .select_from(AreaRule)
                .where(AreaRule.status == "published")
            )
            or 0
        ),
        "occasions_published": int(
            await session.scalar(
                select(func.count())
                .select_from(Occasion)
                .where(Occasion.status == "published")
            )
            or 0
        ),
        "area_users": int(
            await session.scalar(
                select(func.count())
                .select_from(AreaUser)
                .where(AreaUser.active.is_(True))
            )
            or 0
        ),
        "guards": await _count(session, ConversationGuard),
        "recommendations": await _count(session, ConversationRecommendation),
        "active_flows": int(
            await session.scalar(
                select(func.count())
                .select_from(ConversationFlow)
                .where(ConversationFlow.status == "active")
            )
            or 0
        ),
    }

    fallbacks = int(
        await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.created_at >= since,
                Message.direction == "out",
                or_(
                    Message.text.ilike("%No pude procesar%"),
                    Message.text.ilike("%No quiero dejarte%"),
                    Message.text.ilike("%No te entendí%"),
                    Message.text.ilike("%No quiero repetirte%"),
                ),
            )
        )
        or 0
    )

    alerts: list[dict] = []
    if sync.get("failed") or (task.get("last_result") not in (0, None)):
        alerts.append(
            {
                "level": "critical",
                "title": "Sincronización VTEX con error",
                "detail": "Revisá el último log de sincronización.",
            }
        )
    elif not task.get("available"):
        alerts.append(
            {
                "level": "warning",
                "title": "No se pudo leer el estado de la tarea VTEX",
                "detail": "Revisá el Programador de tareas de Windows.",
            }
        )
    if sync.get("at"):
        try:
            synced_at = datetime.fromisoformat(str(sync["at"]))
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)
            if now - synced_at > timedelta(hours=36):
                alerts.append(
                    {
                        "level": "warning",
                        "title": "Sincronización VTEX antigua",
                        "detail": "La última sincronización tiene más de 36 horas.",
                    }
                )
        except ValueError:
            pass
    if not api.get("ok"):
        alerts.append(
            {
                "level": "critical",
                "title": "API de integración no responde",
                "detail": api.get("detail") or "Sin detalle",
            }
        )
    if settings.wa_dry_run:
        alerts.append(
            {
                "level": "warning",
                "title": "WhatsApp en modo prueba",
                "detail": "WA_DRY_RUN está activo.",
            }
        )
    if "trycloudflare" in (settings.public_base_url or ""):
        alerts.append(
            {
                "level": "warning",
                "title": "Túnel temporal",
                "detail": "La URL pública usa trycloudflare.",
            }
        )
    if counts["handoffs_open"] > 5:
        alerts.append(
            {
                "level": "warning",
                "title": "Handoffs acumulados",
                "detail": f"{counts['handoffs_open']} casos abiertos.",
            }
        )
    if counts["rules_published"] == 0:
        alerts.append(
            {
                "level": "warning",
                "title": "Sin reglas publicadas",
                "detail": "El bot no tiene reglas de área activas.",
            }
        )

    overall = "ok"
    if any(alert["level"] == "critical" for alert in alerts):
        overall = "critical"
    elif alerts:
        overall = "attention"

    return {
        "generated_at": now.isoformat(),
        "overall": overall,
        "bot": {
            "ok": True,
            "mode": settings.sap_mode,
            "public_base_url": settings.public_base_url,
            "whatsapp_number": settings.wa_business_number,
            "dry_run": settings.wa_dry_run,
        },
        "api": api,
        "sync": {
            **sync,
            "task": task,
            "failed": sync.get("failed")
            or (task.get("last_result") not in (0, None)),
        },
        "counts": counts,
        "quality": {"fallbacks_24h": fallbacks, "tools": tools},
        "funnel": await funnel.stats(session, 30),
        "search_gaps": await funnel.search_gaps(session, 30),
        "qa": await qa.scan(session, 72),
        "latency": metrics.summary(200),
        "tokens": metrics.tokens_summary(500),
        "alerts": alerts,
    }
