"""Asistente conversacional para crear configuración desde la consola.

El usuario escribe lo que quiere en lenguaje natural. El asistente
interpreta, pide lo que falta y, **cuando la persona confirma**, crea el
elemento en la base (o en la base de conocimiento).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .api_knowledge import _admin
from .db import get_session
from .runtime import agent as agente_runtime
from .services import admin_assistant, area_rules, occasion_store

router = APIRouter(
    tags=["assistant"], dependencies=[Depends(_admin)], prefix="/admin"
)


class Message(BaseModel):
    role: str = "user"
    content: str = Field(min_length=1, max_length=2000)


class ChatPayload(BaseModel):
    tipo: str
    mensajes: list[Message] = Field(min_length=1, max_length=20)


class CrearPayload(BaseModel):
    tipo: str
    borrador: dict


@router.post("/assistant/chat")
async def assistant_chat(payload: ChatPayload) -> dict:
    """Interpreta lo que el usuario quiere crear y dice qué falta."""
    if payload.tipo not in admin_assistant.TIPOS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo inválido. Usá: {', '.join(admin_assistant.TIPOS)}",
        )
    mensajes = [m.model_dump() for m in payload.mensajes]
    resultado = await admin_assistant.conversar(
        agente_runtime, payload.tipo, mensajes
    )
    if resultado is None:
        raise HTTPException(
            status_code=503,
            detail="El asistente no pudo interpretar el pedido. Probá de nuevo.",
        )
    return resultado


def _faltantes(tipo: str, borrador: dict) -> list[str]:
    return [
        campo
        for campo in admin_assistant.TIPOS[tipo]["obligatorios"]
        if campo not in borrador
    ]


@router.post("/assistant/crear")
async def assistant_crear(
    payload: CrearPayload,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Crea el elemento confirmado por la persona."""
    if payload.tipo not in admin_assistant.TIPOS:
        raise HTTPException(status_code=400, detail="Tipo inválido")
    faltantes = _faltantes(payload.tipo, payload.borrador)
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan datos: {', '.join(faltantes)}",
        )
    datos = payload.borrador

    if payload.tipo == "regla":
        try:
            regla = await area_rules.create_rule(
                session,
                area=str(datos["area"]),
                name=str(datos["name"]),
                rule_type=str(datos["rule_type"]),
                condition=datos.get("condition") or {},
                action=datos.get("action") or {},
                priority=int(datos.get("priority") or 0),
                status=str(datos.get("status") or "published"),
                changed_by="asistente",
            )
        except Exception as exc:  # noqa: BLE001 - se informa al usuario
            raise HTTPException(
                status_code=400, detail=str(exc)[:200]
            ) from exc
        return {
            "ok": True,
            "tipo": "regla",
            "id": regla.id,
            "nombre": regla.name,
            "estado": regla.status,
        }

    if payload.tipo == "ocasion":
        try:
            def lista(valor) -> list[str]:
                if isinstance(valor, list):
                    return [str(item).strip() for item in valor if str(item).strip()]
                if isinstance(valor, str):
                    return [
                        item.strip()
                        for item in valor.split("")
                        if item.strip()
                    ]
                return []

            ocasion = await occasion_store.create_occasion(
                session,
                name=str(datos["name"]),
                aliases=lista(datos.get("aliases")),
                direct=lista(datos.get("direct")),
                exclude=[],
                exclude_categories=[],
                bridges=[],
                priority=int(datos.get("priority") or 0),
                status=str(datos.get("status") or "published"),
                changed_by="asistente",
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400, detail=str(exc)[:200]
            ) from exc
        return {
            "ok": True,
            "tipo": "ocasion",
            "id": ocasion.id,
            "nombre": ocasion.name,
            "estado": ocasion.status,
        }

    # Conocimiento: se escribe el archivo y queda disponible para el bot.
    from . import api_knowledge

    slug = admin_assistant.slug(str(datos.get("slug") or datos["title"]))
    articulo = api_knowledge._escribir(
        slug,
        api_knowledge.KnowledgePayload(
            title=str(datos["title"]),
            status=str(datos.get("status") or "published"),
            tags=str(datos.get("tags") or ""),
            content=str(datos["content"]),
        ),
    )
    return {
        "ok": True,
        "tipo": "conocimiento",
        "slug": articulo["slug"],
        "titulo": articulo["title"],
        "estado": articulo["status"],
    }
