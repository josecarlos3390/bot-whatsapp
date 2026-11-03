"""Auditoría de coherencia sobre conversaciones reales.

Toma los mensajes de los clientes de los últimos días, los vuelve a pasar por
el bot (en una conversación limpia) y marca respuestas incoherentes:

- dice «no tengo X» cuando el catálogo tiene X
- abre la ficha de un producto que no tiene que ver con lo pedido
- contesta con una pregunta sin mostrar lo que ya tenía

Uso:
    python -m scripts.auditar_coherencia
    python -m scripts.auditar_coherencia --dias 15 --limite 80
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agent import Agent
from app.db import SessionLocal
from app.models import Contact, Conversation, Message
from app.services import coherencia

# Solo mensajes con contenido de búsqueda; los botones no se auditan.
ACCION = re.compile(r"^[a-z]+:", re.IGNORECASE)


def _contacto_prueba(wa_id: str) -> Contact:
    return Contact(wa_id=wa_id, phone_e164=f"+{wa_id}", name="Auditoría")


async def _revisar(session, texto: str) -> list[dict]:
    hallazgos: list[dict] = []
    contacto = _contacto_prueba(f"audit-{uuid.uuid4().hex[:8]}")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    agente = Agent()
    try:
        respuesta = await agente.handle(session, contacto, texto)
    except Exception as exc:  # noqa: BLE001 - se reporta y sigue
        await session.rollback()
        return [{"tipo": "excepcion", "mensaje": texto, "detalle": str(exc)[:120]}]

    unido = " ".join(m.text or "" for m in respuesta.messages)

    ficha = await coherencia.contradice_al_catalogo(session, texto, unido)
    if ficha:
        hallazgos.append(ficha)

    if not respuesta.messages:
        hallazgos.append({"tipo": "sin_respuesta", "mensaje": texto})
        return hallazgos

    primera = respuesta.messages[0]
    ya_mostro = any(
        m.kind in ("list", "buttons", "image") for m in respuesta.messages
    )
    if not ya_mostro:
        aviso = coherencia.pregunto_sin_mostrar(primera.text or "")
        # Preguntar está bien si no hay nada que mostrar: solo se marca
        # cuando el catálogo sí tenía algo para ese pedido.
        if aviso and await coherencia.existe_producto(session, texto):
            hallazgos.append({**aviso, "mensaje": texto})
    return hallazgos


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, default=7)
    parser.add_argument("--limite", type=int, default=40)
    args = parser.parse_args()

    desde = datetime.now(timezone.utc) - timedelta(days=args.dias)
    async with SessionLocal() as session:
        filas = (
            await session.scalars(
                select(Message.text)
                .where(
                    Message.direction == "in",
                    Message.type == "text",
                    Message.created_at >= desde,
                    Message.text.is_not(None),
                )
                .order_by(Message.created_at.desc())
                .limit(args.limite * 4)
            )
        ).all()

        vistos: set[str] = set()
        textos = []
        for texto in filas:
            limpio = (texto or "").strip()
            if not limpio or limpio.lower() in vistos:
                continue
            if ACCION.match(limpio) or limpio.startswith(("product:", "cat:")):
                continue
            vistos.add(limpio.lower())
            textos.append(limpio)
            if len(textos) >= args.limite:
                break

        print(f"Mensajes reales a revisar: {len(textos)}\n")
        hallazgos = []
        for texto in textos:
            for hallazgo in await _revisar(session, texto):
                hallazgos.append(hallazgo)

        if not hallazgos:
            print("Sin incoherencias detectadas.")
            return 0

        por_tipo: dict[str, int] = {}
        for hallazgo in hallazgos:
            por_tipo[hallazgo["tipo"]] = por_tipo.get(hallazgo["tipo"], 0) + 1
            print(f"· [{hallazgo['tipo']}] {hallazgo.get('mensaje', '')[:80]}")
            for clave in ("fragmento", "producto", "detalle", "respuesta", "faltan"):
                if hallazgo.get(clave):
                    print(f"     {clave}: {str(hallazgo[clave])[:110]}")
            print()
        print("Resumen:", por_tipo)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
