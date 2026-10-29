"""Reinicia las conversaciones y avisa a los contactos reales.

1. Copia de seguridad de la base.
2. Borra conversaciones, mensajes, handoffs, flujos y estados (mantiene los
   contactos, que son la identidad).
3. Envía un mensaje de invitación a los contactos que escribieron en las
   últimas 24 h (fuera de esa ventana Meta exige plantilla aprobada).

Uso:
    python -m scripts.reiniciar_y_avisar            # simulación
    python -m scripts.reiniciar_y_avisar --confirmar
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    ConversationFlow,
    ConversationState,
    Handoff,
    Message,
)
from app.whatsapp import WhatsAppClient

DB = Path("dev.db")
INVITACION = (
    "¡Hola! 👋 Soy *Rohi*, la asesora virtual de ROHO Homecenter 🏡\n\n"
    "Estoy en etapa de entrenamiento: me están enseñando a atender mejor, "
    "y tu ayuda vale muchísimo 🙌\n\n"
    "Podés hacerme preguntas como si estuvieras comprando: precios, stock, "
    "envíos, garantías, o pedirme algo para tu casa.\n\n"
    "Cada consulta me ayuda a aprender 💡 y si algo no lo sé, te lo digo y "
    "aviso a una persona del equipo.\n\n"
    "¿Te animás a probarme? Escribime lo que quieras 👇"
)
TELEFONO_OK = re.compile(r"^\+\d{8,15}$")


def _es_prueba(wa_id: str, telefono: str | None) -> bool:
    if not TELEFONO_OK.match((telefono or "").strip()):
        return True
    if re.search(r"[a-fA-F]", wa_id or ""):
        return True
    return False


async def contactos_recientes(session, horas: int = 24) -> list[dict]:
    """Contactos que escribieron en la ventana (pueden recibir sin plantilla)."""
    desde = datetime.now(timezone.utc) - timedelta(hours=horas)
    filas = (
        await session.execute(
            select(Contact, func.max(Message.created_at))
            .join(Conversation, Conversation.contact_id == Contact.id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.direction == "in", Message.created_at >= desde)
            .group_by(Contact.id)
        )
    ).all()
    return [
        {"contacto": contacto, "ultimo": ultimo}
        for contacto, ultimo in filas
        if not _es_prueba(contacto.wa_id, contacto.phone_e164)
    ]


async def limpiar(session) -> dict:
    conversaciones = (await session.scalars(select(Conversation.id))).all()
    if conversaciones:
        await session.execute(
            delete(Message).where(Message.conversation_id.in_(conversaciones))
        )
        await session.execute(
            delete(Handoff).where(Handoff.conversation_id.in_(conversaciones))
        )
        await session.execute(
            delete(ConversationFlow).where(
                ConversationFlow.conversation_id.in_(conversaciones)
            )
        )
        await session.execute(
            delete(ConversationState).where(
                ConversationState.conversation_id.in_(conversaciones)
            )
        )
        await session.execute(
            delete(Conversation).where(Conversation.id.in_(conversaciones))
        )
        await session.commit()
    return {"conversaciones": len(conversaciones)}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    parser.add_argument("--horas", type=int, default=24)
    args = parser.parse_args()

    async with SessionLocal() as session:
        destinatarios = await contactos_recientes(session, args.horas)
        print("contactos que pueden recibir sin plantilla:")
        for fila in destinatarios:
            contacto = fila["contacto"]
            print(f"  {contacto.name or '(sin nombre)'} | {contacto.phone_e164}")

        if not args.confirmar:
            print("\nSimulación: no se borró nada ni se envió nada.")
            print("Para ejecutar: --confirmar")
            return 0

        if DB.exists():
            respaldo = DB.with_name(
                f"dev-backup-{datetime.now():%Y%m%d-%H%M%S}.db"
            )
            shutil.copy2(DB, respaldo)
            print(f"\nrespaldo: {respaldo.name}")

        borrado = await limpiar(session)
        print(f"conversaciones borradas: {borrado['conversaciones']}")

    cliente = WhatsAppClient()
    enviados = 0
    fallidos = 0
    try:
        for fila in destinatarios:
            contacto = fila["contacto"]
            destino = (contacto.phone_e164 or "").lstrip("+")
            try:
                await cliente.send_text(destino, INVITACION)
                enviados += 1
                print(f"  enviado a {destino}")
            except Exception as exc:  # noqa: BLE001 - se informa y se sigue
                fallidos += 1
                print(f"  FALLÓ {destino}: {str(exc)[:120]}")
            await asyncio.sleep(2)
    finally:
        await cliente.close()

    print(f"\nenviados: {enviados} | fallidos: {fallidos}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
