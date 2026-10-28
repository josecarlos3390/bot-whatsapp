"""No repetir exactamente la misma respuesta que ya se envió.

El fuzzing encontró que, ante un cliente enojado, el bot podía contestar dos
veces el mismo texto. La detección de bucles miraba el historial del guard;
esto lo cubre en la salida, sin importar qué camino generó la respuesta.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, Conversation, Message


def _normalizar(texto: str) -> str:
    limpio = re.sub(r"\s+", " ", (texto or "").strip().lower())
    return limpio[:400]


async def repetida(
    session: AsyncSession, contact: Contact, answer: str
) -> bool:
    """¿La respuesta es igual a la última que se envió?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    ultimo = await session.scalar(
        select(Message.text)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "out",
            Message.text.is_not(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    if not ultimo:
        return False
    return _normalizar(ultimo) == _normalizar(answer) and len(_normalizar(ultimo)) > 20


def variante(contact: Contact) -> str:
    """Respuesta distinta para no repetir el mismo texto."""
    nombre = (contact.name or "").split(" ")[0]
    saludo = f"{nombre}, " if nombre else ""
    return (
        f"{saludo}ya te pasé lo que tengo sobre eso. Si necesitás confirmar "
        "un dato puntual (precio final, stock o plazo), te paso con un asesor "
        "para que te lo confirme."
    )


def _parecido(a: str, b: str, umbral: float = 0.75) -> bool:
    """Similitud de texto (0 a 1) por difflib."""
    from difflib import SequenceMatcher

    uno, otro = _normalizar(a), _normalizar(b)
    if not uno or not otro:
        return False
    return SequenceMatcher(None, uno, otro).ratio() >= umbral


async def cliente_repite(
    session: AsyncSession, contact: Contact, texto: str, limite: int = 6
) -> bool:
    """¿El cliente ya preguntó lo mismo en los mensajes anteriores?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    filas = (
        await session.scalars(
            select(Message.text)
            .where(
                Message.conversation_id == conversacion.id,
                Message.direction == "in",
                Message.text.is_not(None),
            )
            .order_by(Message.created_at.desc())
            .limit(limite + 1)
        )
    ).all()
    # La primera es el mensaje actual (ya guardado antes de responder).
    anteriores = list(filas[1:]) if filas else []
    return any(_parecido(texto or "", previo or "") for previo in anteriores)


async def respuesta_parecida(
    session: AsyncSession, contact: Contact, answer: str
) -> bool:
    """¿La respuesta se parece a la anterior (no idéntica)?"""
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contact.id)
    )
    if conversacion is None:
        return False
    ultimo = await session.scalar(
        select(Message.text)
        .where(
            Message.conversation_id == conversacion.id,
            Message.direction == "out",
            Message.text.is_not(None),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return bool(ultimo) and _parecido(ultimo or "", answer or "")


def cambio_de_enfoque(contact: Contact) -> str:
    """Mensaje cuando el cliente insiste y el bot iba a repetir."""
    nombre = (contact.name or "").split(" ")[0]
    saludo = f"{nombre}, " if nombre else ""
    return (
        f"{saludo}entiendo que lo que te mostré no te sirvió. Para no "
        "repetirte la misma información: decime qué te falta (medida, marca "
        "o presupuesto) y lo busco de nuevo, o te paso con un asesor que lo "
        "revise con vos."
    )


def skus_de(reply) -> list[str]:
    """SKUs que muestra una respuesta (listas y botones)."""
    encontrados: list[str] = []
    for mensaje in getattr(reply, "messages", []) or []:
        for seccion in (getattr(mensaje, "sections", None) or []):
            for fila in (seccion.get("rows") or []):
                identificador = str(fila.get("id") or "")
                if identificador.startswith(("product:", "add:")):
                    sku = identificador.split(":")[1]
                    if sku and sku not in encontrados:
                        encontrados.append(sku)
        for boton in (getattr(mensaje, "buttons", None) or []):
            identificador = str(boton.get("id") or "")
            if identificador.startswith(("product:", "add:")):
                sku = identificador.split(":")[1]
                if sku and sku not in encontrados:
                    encontrados.append(sku)
    return encontrados


def repite_el_mismo_listado(
    anteriores: list[str] | None, actuales: list[str]
) -> bool:
    """¿Se están mostrando exactamente los mismos productos que antes?"""
    if not actuales or not anteriores:
        return False
    return set(actuales) == set(anteriores)


def repite_parcial(
    anteriores: list[str] | None, actuales: list[str], umbral: float = 0.6
) -> bool:
    """¿La mayoría de los productos ya se mostraron antes?

    El caso exacto ya se cubre aparte; esto atrapa el listado que cambia un
    producto y repite el resto.
    """
    if not anteriores or not actuales:
        return False
    if len(anteriores) < 2 or len(actuales) < 2:
        return False
    previos = set(anteriores)
    repetidos = sum(1 for sku in actuales if sku in previos)
    return repetidos / len(actuales) >= umbral


def filtro_sugerido(contact: Contact) -> str:
    """Pregunta que destraba cuando el listado se repite."""
    nombre = (contact.name or "").split(" ")[0]
    saludo = f"{nombre}, " if nombre else ""
    return (
        f"{saludo}ya te mostré varias de esas opciones. Para no repetirte el "
        "mismo listado: ¿querés que filtre por medida, marca o precio, o te "
        "paso con un asesor?"
    )
