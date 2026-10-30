"""Asistente conversacional para crear configuración desde la consola."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .api_knowledge import _admin
from .runtime import agent as agente_runtime
from .services import admin_assistant

router = None  # se define abajo para mantener el estilo del proyecto

from fastapi import APIRouter  # noqa: E402

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


@router.post("/assistant/crear")
async def assistant_crear(payload: CrearPayload) -> dict:
    """Crea el elemento confirmado.

    La pantalla muestra el resumen y, si la persona acepta, llama acá con el
    borrador ya completo. El asistente nunca escribe solo.
    """
    if payload.tipo not in admin_assistant.TIPOS:
        raise HTTPException(status_code=400, detail="Tipo inválido")
    faltantes = [
        campo
        for campo in admin_assistant.TIPOS[payload.tipo]["obligatorios"]
        if campo not in payload.borrador
    ]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan datos: {', '.join(faltantes)}",
        )
    # La creación real la hacen los endpoints existentes; acá se devuelve el
    # borrador listo para que la pantalla los llame.
    return {
        "ok": True,
        "tipo": payload.tipo,
        "borrador": payload.borrador,
    }
