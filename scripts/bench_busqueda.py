"""Banco de pruebas de búsqueda: 50 consultas con lo que deberían devolver.

Sirve para medir la búsqueda antes y después de cambiarla (BM25, typos,
rerank). Cada caso declara palabras que deben aparecer en el nombre del
producto encontrado.

Uso:
    python -m scripts.bench_busqueda
    python -m scripts.bench_busqueda --detalle
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.services import catalog

# (consulta del cliente, palabras que deben aparecer en el producto)
CASOS: list[tuple[str, tuple[str, ...]]] = [
    ("taladro percutor", ("taladro",)),
    ("taladro inalámbrico", ("taladro",)),
    ("brocas para metal", ("broca",)),
    ("brocas para concreto", ("broca",)),
    ("destornillador", ("destornill", "desarmador")),
    ("alicate", ("alicate",)),
    ("llave inglesa", ("llave",)),
    ("martillo", ("martillo",)),
    ("sierra circular", ("sierra",)),
    ("nivel de burbuja", ("nivel",)),
    ("cinta métrica", ("cinta",)),
    ("pintura para pared", ("pintura",)),
    ("pintura blanca", ("pintura", "blanco", "blanca")),
    ("pintura en aerosol", ("aerosol", "spray")),
    ("rodillo para pintar", ("rodillo",)),
    ("brocha", ("brocha",)),
    ("impermeabilizante", ("impermeabiliz",)),
    ("sellador de silicona", ("silicona", "sellador")),
    ("pegamento", ("pegamento", "pega", "adhesivo")),
    ("colchón de 2 plazas", ("colch",)),
    ("colchón de 1 plaza", ("colch",)),
    ("almohada", ("almohada",)),
    ("cubrecama", ("cubrecama",)),
    ("toalla de baño", ("toalla",)),
    ("juego de sábanas", ("sábana", "sabana")),
    ("cortina roller", ("cortina", "roller")),
    ("alfombra", ("alfombra",)),
    ("espejo para baño", ("espejo",)),
    ("repisa", ("repisa", "estante")),
    ("organizador de baño", ("organizador",)),
    ("basurero", ("basurero",)),
    ("accesorio de cocina", ("cocina",)),
    ("plato", ("plato",)),
    ("vaso", ("vaso",)),
    ("olla", ("olla",)),
    ("parrilla", ("parrilla",)),
    ("carbón", ("carbón", "carbon")),
    ("manguera de jardín", ("manguera",)),
    ("regadera", ("regadera",)),
    ("maceta", ("maceta",)),
    ("foco led", ("foco", "led")),
    ("lámpara de techo", ("lámpara", "lampara", "plafón")),
    ("extension eléctrica", ("extensión", "extension", "alargador")),
    ("enchufe", ("enchufe", "tomacorriente")),
    ("ventilador", ("ventilador",)),
    ("aire acondicionado", ("aire", "acondicionado")),
    ("lavadora", ("lavadora", "lavarropas")),
    ("heladera", ("helader", "refrig")),
    ("televisor de 43 pulgadas", ("tv", "televisor")),
    ("microondas", ("microonda",)),
    # Consultas que fallaron en conversaciones reales.
    ("tazas de cerámica", ("taza",)),
    ("termo eléctrico", ("termo",)),
    ("mochila escolar", ("mochila",)),
    ("plancha de cabello", ("plancha",)),
    ("cable cargador iphone", ("cable",)),
    ("cocina 4 hornallas", ("cocina",)),
]


def _aciertos(nombre: str, espera: tuple[str, ...]) -> bool:
    texto = (nombre or "").lower()
    return any(clave in texto for clave in espera)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detalle", action="store_true")
    parser.add_argument("--limite", type=int, default=3)
    parser.add_argument(
        "--agente",
        action="store_true",
        help="Mide lo que ve el cliente (respuesta del agente).",
    )
    args = parser.parse_args()

    aciertos_1 = 0
    aciertos_n = 0
    suma_rr = 0.0
    fallos: list[tuple[str, str]] = []

    async with SessionLocal() as session:
        for consulta, espera in CASOS:
            if args.agente:
                from app.agent import Agent
                from app.models import Contact, Conversation

                sufijo = f"b{abs(hash(consulta)) % 100000}"
                contacto = Contact(
                    wa_id=sufijo, phone_e164=f"+0{sufijo[:9]}", name="Bench"
                )
                session.add(contacto)
                await session.flush()
                session.add(Conversation(contact_id=contacto.id))
                await session.commit()
                agente = Agent()
                respuesta = await agente.handle(session, contacto, consulta)
                respuesta = await agente.postprocess(
                    session, contacto, consulta, respuesta
                )
                texto = "\n".join(
                    m.text or "" for m in respuesta.messages
                )
                from sqlalchemy import delete

                from app.models import ConversationFlow, ConversationState, Message

                conversacion = await session.scalar(
                    select(Conversation.id).where(
                        Conversation.contact_id == contacto.id
                    )
                )
                for tabla in (Message, ConversationFlow, ConversationState):
                    if conversacion:
                        await session.execute(
                            delete(tabla).where(
                                tabla.conversation_id == conversacion
                            )
                        )
                await session.execute(
                    delete(Conversation).where(
                        Conversation.contact_id == contacto.id
                    )
                )
                await session.execute(
                    delete(Contact).where(Contact.id == contacto.id)
                )
                await session.commit()
                nombres = [texto]
            else:
                productos = await catalog.search_items(
                    session, consulta, limit=args.limite
                )
                nombres = [p.name for p in productos]
            posicion = next(
                (
                    indice
                    for indice, nombre in enumerate(nombres, start=1)
                    if _aciertos(nombre, espera)
                ),
                None,
            )
            if posicion == 1:
                aciertos_1 += 1
            if posicion:
                aciertos_n += 1
                suma_rr += 1 / posicion
            else:
                fallos.append(
                    (consulta, nombres[0] if nombres else "(nada)")
                )
            if args.detalle:
                marca = "OK " if posicion == 1 else ("TOP" if posicion else "FALLA")
                primero = nombres[0][:58] if nombres else "(nada)"
                print(f"[{marca}] {consulta:<28} → {primero}")

    total = len(CASOS)
    print(f"\nconsultas: {total}")
    print(f"acierta en el 1°: {aciertos_1}/{total} ({aciertos_1 / total:.0%})")
    print(f"acierta en el top {args.limite}: {aciertos_n}/{total} ({aciertos_n / total:.0%})")
    print(f"MRR: {suma_rr / total:.2f}")

    if fallos:
        print("\nfallos:")
        for consulta, primero in fallos:
            print(f"  {consulta:<28} → {primero[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
