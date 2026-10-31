"""Probar productos que no vendemos: ¿sugiere algo coherente?

Simula la foto y el texto para varios productos del mismo tipo y muestra qué
responde el bot, para detectar sugerencias sin sentido.

Uso:
    python -m scripts.caso_no_vendemos
"""

from __future__ import annotations

import asyncio
import uuid

from app.agent import Agent
from app.db import SessionLocal
from app.flows import media as media_flow
from app.models import Contact, Conversation

CASOS = [
    {"objeto": "monitor", "categoria": "electrónica", "marca": "Samsung"},
    {"objeto": "impresora", "categoria": "electrónica", "marca": "HP"},
    {"objeto": "licuadora industrial", "categoria": "electrodomésticos", "marca": ""},
    {"objeto": "lavavajillas", "categoria": "electrodomésticos", "marca": "Bosch"},
    {"objeto": "secadora", "categoria": "electrodomésticos", "marca": "LG"},
    {"objeto": "freidora de aire", "categoria": "electrodomésticos", "marca": ""},
    {"objeto": "telescopio", "categoria": "otros", "marca": ""},
    {"objeto": "consola de videojuegos", "categoria": "electrónica", "marca": "Sony"},
]


async def _contacto(session, nombre: str):
    wa = f"5917{uuid.uuid4().hex[:9]}"
    contacto = Contact(wa_id=wa, phone_e164=f"+{wa}", name=nombre)
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def _imagen(session, caso: dict) -> str:
    contacto = await _contacto(session, f"img {caso['objeto']}")
    descripcion = {
        "objeto": caso["objeto"],
        "marca": caso["marca"],
        "categoria": caso["categoria"],
        "atributos": "",
        "intencion": "",
    }

    async def _falsa(archivo, mime):
        return descripcion

    async def _descarga(media_id):
        return (b"x", "image/jpeg")

    original = media_flow.vision.describe
    original_descarga = media_flow.media_service.download
    media_flow.vision.describe = _falsa
    media_flow.media_service.download = _descarga
    try:
        respuesta = await media_flow.reply(
            Agent(), session, contacto, {"media_id": "x", "kind": "image"}, texto=""
        )
    finally:
        media_flow.vision.describe = original
        media_flow.media_service.download = original_descarga
    if respuesta is None:
        return "(sin respuesta)"
    return " | ".join(
        (m.text or "").replace("\n", " ")[:220] for m in respuesta.messages
    )


async def _texto(session, caso: dict) -> str:
    contacto = await _contacto(session, f"txt {caso['objeto']}")
    agente = Agent()
    respuesta = await agente.handle(session, contacto, f"busco una {caso['objeto']}")
    respuesta = await agente.postprocess(
        session, contacto, f"busco una {caso['objeto']}", respuesta
    )
    return " | ".join(
        (m.text or "").replace("\n", " ")[:220] for m in respuesta.messages
    )


async def main() -> int:
    async with SessionLocal() as session:
        for caso in CASOS:
            print(f"=== {caso['objeto']}")
            print("  FOTO:", await _imagen(session, caso))
            print("  TEXTO:", await _texto(session, caso))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
