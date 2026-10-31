"""Revisar lo que escribieron los testers y detectar incoherencias.

Muestra las últimas conversaciones de los números de prueba y marca lo que
suele estar mal: respuestas vacías, mensajes repetidos, derivaciones, textos
internos filtrados.

Uso:
    python -m scripts.revisar_testers
    python -m scripts.revisar_testers --horas 48 --mensajes 30
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contact, Conversation, Handoff, Message

TESTERS = {
    "+59177810716": "JoseKa",
    "+59169006969": "Chipi",
    "+59179050453": "(sin nombre)",
    "+59176012480": "Alejandra",
}

PROHIBIDAS = (
    "contenido de ejemplo",
    "reemplazar por",
    "gracias por contarme",
    "no pude completar",
    "traceback",
    "ninguna capa",
)


def _texto(mensaje: Message) -> str:
    return (mensaje.text or "").strip()


def _marcas(mensajes: list[Message]) -> list[str]:
    """Incoherencias detectadas en la conversación."""
    fallas: list[str] = []
    salientes = [m for m in mensajes if m.direction == "out"]
    for mensaje in salientes:
        texto = _texto(mensaje).lower()
        for prohibida in PROHIBIDAS:
            if prohibida in texto:
                fallas.append(f"«{prohibida}» en un mensaje del bot")
        if not _texto(mensaje) and mensaje.type != "image":
            fallas.append("mensaje del bot vacío")
    # Mismo texto dos veces seguidas.
    anterior = ""
    for mensaje in salientes:
        actual = _texto(mensaje)
        if actual and actual == anterior:
            fallas.append(f"mensaje repetido: «{actual[:40]}»")
        anterior = actual
    return fallas


async def _revisar(session, horas: int, limite: int) -> None:
    desde = datetime.now(timezone.utc) - timedelta(hours=horas)
    for telefono, nombre in TESTERS.items():
        contacto = await session.scalar(
            select(Contact).where(Contact.phone_e164 == telefono)
        )
        if contacto is None:
            print(f"\n=== {nombre} ({telefono}): sin contacto")
            continue
        conversacion = await session.scalar(
            select(Conversation).where(Conversation.contact_id == contacto.id)
        )
        if conversacion is None:
            print(f"\n=== {nombre} ({telefono}): sin conversación")
            continue
        mensajes = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversacion.id)
                .order_by(Message.created_at)
            )
        ).all()
        recientes = [m for m in mensajes if m.created_at and m.created_at >= desde]
        print(
            f"\n=== {nombre} ({telefono}) · {len(recientes)} mensajes "
            f"en {horas} h (total {len(mensajes)})"
        )
        for mensaje in recientes[-limite:]:
            hora = mensaje.created_at.strftime("%d/%m %H:%M")
            quien = "cliente" if mensaje.direction == "in" else "bot    "
            texto = _texto(mensaje).replace("\n", " ")[:110]
            print(f"  {hora} {quien} [{mensaje.type}] {texto}")

        for falla in _marcas(recientes):
            print(f"  ✗ {falla}")

        avisos = (
            await session.scalars(
                select(Handoff)
                .where(Handoff.conversation_id == conversacion.id)
                .order_by(Handoff.created_at.desc())
                .limit(1)
            )
        ).all()
        if avisos:
            aviso = avisos[0]
            print(
                f"  ⤷ derivación: {aviso.status} · "
                f"{(aviso.reason or '')[:70]}"
            )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horas", type=int, default=24)
    parser.add_argument("--mensajes", type=int, default=20)
    args = parser.parse_args()

    async with SessionLocal() as session:
        await _revisar(session, args.horas, args.mensajes)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
