"""Cliente que insiste: pedir una persona, enojarse o repetir.

El bot no debe dejar a alguien esperando en silencio ni insistir con
productos cuando la persona ya pidió hablar con alguien.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import func, select

from ..models import Contact, Conversation, Message

logger = logging.getLogger(__name__)

# Pide explícitamente una persona.
PIDe_HUMANO = re.compile(
    r"(quiero|necesito|prefiero|pasame|comunicame|derivame|llamame).{0,20}"
    r"(persona|humano|asesor|alguien|vendedor|ejecutivo|real)"
    r"|no\s+quiero\s+(hablar\s+con\s+)?(un\s+)?(bot|robot|m[aá]quina)"
    r"|atendeme\s+vos"
    r"|hablar\s+con\s+una\s+persona",
    re.IGNORECASE,
)

# Insiste después de haber pedido.
INSISTE = re.compile(
    r"^(hola\??|hola\s+hola|sigue\s+ahi|estas\s+ahi|hay\s+alguien|"
    r"me\s+escuchas|respondeme|contestame|por\s+favor|urgente|ya\s+ya)$",
    re.IGNORECASE,
)

MAXIMO_INSISTENCIAS = 2


def pide_humano(texto: str) -> bool:
    """¿Está pidiendo una persona de verdad?"""
    return bool(PIDe_HUMANO.search(texto or ""))


def insiste(texto: str) -> bool:
    """¿Es un reclamo de atención sin contenido nuevo?"""
    return bool(INSISTE.match((texto or "").strip()))


async def esperando(session, contacto: Contact) -> int:
    """Cuántos mensajes escribió desde que pidió un asesor."""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contacto.id)
    )
    if conversacion is None:
        return 0
    from ..services import handoffs

    abierto = await session.scalar(
        select(handoffs.Handoff)
        .where(
            handoffs.Handoff.conversation_id == conversacion.id,
            handoffs.Handoff.status.in_({"pending", "queued", "active"}),
        )
        .order_by(handoffs.Handoff.created_at.desc())
        .limit(1)
    )
    if abierto is None:
        return 0
    total = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "in",
            Message.created_at > abierto.created_at,
        )
    )
    return int(total or 0)


def agradecer(nombre: str | None = None) -> str:
    quien = f" {nombre}" if nombre else ""
    return (
        f"Gracias por la paciencia{quien} 🙏 Ya avisé al equipo y un asesor "
        "te escribe por acá en los próximos minutos.\n\n"
        "Si querés adelantar, dejame tu consulta en un mensaje y se la paso "
        "con tu nombre."
    )


def sin_respuesta(nombre: str | None = None) -> str:
    quien = f" {nombre}" if nombre else ""
    return (
        f"{quien.strip() or 'Hola'}, seguimos con tu caso: el equipo ya lo "
        "tiene y te escriben por acá. Si preferís, dejame el detalle en un "
        "mensaje y lo sumo."
    )

async def ya_avisamos(session, contacto: Contact, marca: str) -> bool:
    """¿Ya se le mandó ese aviso desde que está esperando?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contacto.id)
    )
    if conversacion is None:
        return False
    fila = await session.scalar(
        select(Message.id)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "out",
            Message.text.contains(marca),
        )
        .limit(1)
    )
    return fila is not None
