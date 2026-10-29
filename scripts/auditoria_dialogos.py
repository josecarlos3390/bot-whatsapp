"""Auditoría de diálogos: cada pregunta del bot tiene su respuesta natural.

El bot hace preguntas ("¿alguna marca en particular?") y el cliente contesta
con frases que no son productos. Este script corre esos diálogos y falla si el
bot responde "no tengo", si no avanza o si repite.

Uso:
    python -m scripts.auditoria_dialogos
    python -m scripts.auditoria_dialogos --caso marca
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from app.agent import Agent
from app.db import SessionLocal
from app.models import Contact, Conversation

# Frases que indican que el bot no entendió.
PROHIBIDAS = (
    "no tengo eso exacto",
    "no tengo nada para",
    "no encontré productos con ese criterio",
    "no reconozco",
)

# Cada caso: mensajes del cliente y qué debería aparecer en alguna respuesta.
CASOS: list[dict] = [
    {
        "id": "marca",
        "mensajes": ["busco un colchón", "no importa la marca, mostrame opciones"],
        "espera": ["colchón", "colchon", "opciones"],
    },
    {
        "id": "medida",
        "mensajes": ["busco un colchón", "de 2 plazas"],
        "espera": ["2 plazas", "140", "190"],
    },
    {
        "id": "elegidas",
        "mensajes": ["busco un colchón", "mostrame las más elegidas"],
        "espera": ["elegidas", "opciones", "vendidas"],
    },
    {
        "id": "baratos",
        "mensajes": ["busco un taladro", "mostrame los más baratos"],
        "espera": ["barato", "Bs"],
    },
    {
        "id": "categoria",
        "mensajes": ["catalog", "cat:sala", "sofás"],
        "espera": ["sofá", "sofa"],
    },
    {
        "id": "asesor",
        "mensajes": ["quiero hablar con una persona"],
        "espera": ["asesor", "equipo", "persona"],
    },
    {
        "id": "pedido-doc",
        "mensajes": ["quiero revisar mi pedido", "mi carnet es 5403339"],
        "espera": ["pedido", "compras", "estado"],
    },
    {
        "id": "envio",
        "mensajes": ["¿hacen envíos a Santa Cruz capital?"],
        "espera": ["envío", "envio", "entrega"],
    },
    {
        "id": "garantia",
        "mensajes": ["¿qué garantía tiene una lavadora?"],
        "espera": ["garantía", "garantia", "meses"],
    },
    {
        "id": "visitas",
        "mensajes": ["necesito algo para distraer a las visitas"],
        "espera": ["televisor", "juego", "opciones", "propongo"],
    },
]


def evaluar(salidas: list[str], espera: list[str]) -> tuple[bool, str]:
    """Decide si el caso pasó."""
    texto = " ".join(salidas).lower()
    for prohibida in PROHIBIDAS:
        if prohibida in texto:
            return False, f"respondió «{prohibida}»"
    if not any(clave.lower() in texto for clave in espera):
        return False, "no menciona lo esperado"
    return True, "ok"


async def correr(caso: dict) -> tuple[bool, str, list[str]]:
    async with SessionLocal() as session:
        sufijo = uuid.uuid4().hex[:8]
        contacto = Contact(
            wa_id=f"audit{sufijo}",
            phone_e164=f"+0{sufijo}",
            name="Auditoría",
        )
        session.add(contacto)
        await session.flush()
        session.add(Conversation(contact_id=contacto.id))
        await session.commit()

        salidas: list[str] = []
        for mensaje in caso["mensajes"]:
            agente = Agent()
            respuesta = await agente.handle(session, contacto, mensaje)
            respuesta = await agente.postprocess(
                session, contacto, mensaje, respuesta
            )
            salidas.append(
                " ".join(m.text or "" for m in respuesta.messages)
            )
        ok, motivo = evaluar(salidas, caso["espera"])
        return ok, motivo, salidas


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--caso", default="")
    args = parser.parse_args()

    casos = [c for c in CASOS if not args.caso or c["id"] == args.caso]
    fallos = 0
    for caso in casos:
        ok, motivo, salidas = await correr(caso)
        marca = "OK   " if ok else "FALLA"
        print(f"[{marca}] {caso['id']}: {motivo}")
        if not ok:
            fallos += 1
            for i, salida in enumerate(salidas, start=1):
                print(f"   {i}. {salida[:160]}")

    print(f"\ncasos: {len(casos)} | fallos: {fallos}")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
