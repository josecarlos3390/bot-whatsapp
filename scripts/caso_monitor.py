"""Reproducir el caso de la foto de un monitor y ver qué sugiere el bot.

Uso:
    python -m scripts.caso_monitor
"""

from __future__ import annotations

import asyncio
import uuid

from app.agent import Agent
from app.db import SessionLocal
from app.flows import media as media_flow
from app.models import Contact, Conversation


DESCRIPCION = {
    "objeto": "monitor",
    "marca": "Samsung",
    "categoria": "electrónica",
    "atributos": "pantalla plana, 24 pulgadas, base redonda",
    "intencion": "",
}


async def main() -> int:
    async with SessionLocal() as session:
        wa = f"5917{uuid.uuid4().hex[:9]}"
        contacto = Contact(wa_id=wa, phone_e164=f"+{wa}", name="Caso monitor")
        session.add(contacto)
        await session.flush()
        session.add(Conversation(contact_id=contacto.id))
        await session.commit()

        # Se evita descargar la imagen: se fuerza la descripción.
        async def _falsa(archivo, mime):
            return DESCRIPCION

        async def _descarga(media_id):
            return (b"x", "image/jpeg")

        original_vision = media_flow.vision.describe
        original_descarga = media_flow.media_service.download
        media_flow.vision.describe = _falsa
        media_flow.media_service.download = _descarga
        try:
            agente = Agent()
            respuesta = await media_flow.reply(
                agente,
                session,
                contacto,
                {"media_id": "fake", "kind": "image"},
                texto="",
            )
        finally:
            media_flow.vision.describe = original_vision
            media_flow.media_service.download = original_descarga

        print("traza:", agente.trace[:4])
        if respuesta is None:
            print("sin respuesta")
            return 0
        for mensaje in respuesta.messages:
            texto = (mensaje.text or "").replace("\n", " | ")
            print(f"{mensaje.kind:<7} {texto[:220]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
