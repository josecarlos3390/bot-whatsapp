"""Contactos de prueba: detecta y opcionalmente limpia números inválidos.

Los scripts de simulación crearon contactos con `wa_id` que no es un teléfono
(por ejemplo `5917fed89f005`). No son clientes reales y ensucian las métricas.

Uso:
    python -m scripts.limpiar_contactos_prueba            # solo lista
    python -m scripts.limpiar_contactos_prueba --confirmar # borra
"""

from __future__ import annotations

import argparse
import asyncio
import re
from collections import Counter

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    CustomerProfile,
    Handoff,
    Message,
)

TELEFONO_OK = re.compile(r"^\+\d{8,15}$")


def es_prueba(wa_id: str, telefono: str | None) -> bool:
    """¿El contacto es un artefacto de prueba?"""
    numero = (telefono or "").strip()
    if not TELEFONO_OK.match(numero):
        return True
    # wa_id con letras: generado por un script, no por WhatsApp.
    if re.search(r"[a-fA-F]", wa_id or ""):
        return True
    return False


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmar", action="store_true")
    args = parser.parse_args()

    async with SessionLocal() as session:
        contactos = (await session.scalars(select(Contact))).all()
        pruebas = [
            c for c in contactos if es_prueba(c.wa_id, c.phone_e164)
        ]
        print(f"contactos totales: {len(contactos)}")
        print(f"artefactos de prueba: {len(pruebas)}")
        motivos = Counter(
            "wa_id con letras"
            if re.search(r"[a-fA-F]", c.wa_id or "")
            else "teléfono inválido"
            for c in pruebas
        )
        for motivo, veces in motivos.items():
            print(f"  {motivo}: {veces}")
        for contacto in pruebas[:5]:
            print("   ejemplo:", contacto.wa_id, "|", contacto.phone_e164)

        if not args.confirmar:
            print("\nModo lista: no se borró nada (usar --confirmar).")
            return 0

        ids = [c.id for c in pruebas]
        if not ids:
            return 0
        conversaciones = (
            await session.scalars(
                select(Conversation.id).where(
                    Conversation.contact_id.in_(ids)
                )
            )
        ).all()
        if conversaciones:
            await session.execute(
                delete(Message).where(
                    Message.conversation_id.in_(conversaciones)
                )
            )
            await session.execute(
                delete(Handoff).where(
                    Handoff.conversation_id.in_(conversaciones)
                )
            )
            await session.execute(
                delete(Conversation).where(Conversation.id.in_(conversaciones))
            )
        await session.execute(
            delete(CustomerProfile).where(CustomerProfile.contact_id.in_(ids))
        )
        await session.execute(delete(Contact).where(Contact.id.in_(ids)))
        await session.commit()
        print(f"\nborrados: {len(ids)} contactos y sus conversaciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
