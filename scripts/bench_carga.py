"""Prueba de carga: varios clientes escribiendo a la vez.

Simula N clientes concurrentes con M mensajes cada uno, mide latencia
(p50, p95, máxima) y errores, y borra todo al terminar.

Uso:
    python -m scripts.bench_carga --clientes 10 --mensajes 2
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import uuid

from sqlalchemy import delete, select

from app.agent import Agent
from app.db import SessionLocal
from app.models import (
    Cart,
    CartItem,
    Contact,
    Conversation,
    ConversationFlow,
    ConversationGuard,
    ConversationState,
    Handoff,
    Message,
)

CONSULTAS = [
    "busco un taladro",
    "mostrame televisores",
    "necesito un colchón de 2 plazas",
    "tienen pintura blanca?",
    "quiero ver heladeras",
    "busco una licuadora",
]


async def _cliente(
    numero: int,
    mensajes: int,
    resultados: list,
    consulta_fija: str = "",
) -> None:
    sufijo = uuid.uuid4().hex[:10]
    async with SessionLocal() as session:
        contacto = Contact(
            wa_id=f"carga{sufijo}",
            phone_e164=f"+0{sufijo[:9]}",
            name=f"Cliente {numero}",
        )
        session.add(contacto)
        await session.flush()
        conversacion = Conversation(contact_id=contacto.id)
        session.add(conversacion)
        await session.commit()

        for indice in range(mensajes):
            consulta = consulta_fija or CONSULTAS[
                (numero + indice) % len(CONSULTAS)
            ]
            inicio = time.perf_counter()
            error = ""
            try:
                agente = Agent()
                respuesta = await agente.handle(session, contacto, consulta)
                await agente.postprocess(
                    session, contacto, consulta, respuesta
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"[:120]
            resultados.append(((time.perf_counter() - inicio) * 1000, error))

        # Limpieza del cliente simulado.
        for tabla in (Message, Handoff, ConversationFlow, ConversationState):
            await session.execute(
                delete(tabla).where(tabla.conversation_id == conversacion.id)
            )
        await session.execute(
            delete(ConversationGuard).where(
                ConversationGuard.conversation_id == conversacion.id
            )
        )
        carritos = (
            await session.scalars(
                select(Cart.id).where(Cart.contact_id == contacto.id)
            )
        ).all()
        for carrito in carritos:
            await session.execute(
                delete(CartItem).where(CartItem.cart_id == carrito)
            )
        await session.execute(delete(Cart).where(Cart.contact_id == contacto.id))
        await session.execute(
            delete(Conversation).where(Conversation.id == conversacion.id)
        )
        await session.execute(delete(Contact).where(Contact.id == contacto.id))
        await session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clientes", type=int, default=10)
    parser.add_argument("--mensajes", type=int, default=2)
    parser.add_argument(
        "--consulta",
        default="",
        help="Misma consulta para todos (mide concurrencia pura).",
    )
    args = parser.parse_args()

    resultados: list[tuple[float, str]] = []
    inicio = time.perf_counter()
    await asyncio.gather(
        *[
            _cliente(numero, args.mensajes, resultados, args.consulta)
            for numero in range(args.clientes)
        ]
    )
    total = time.perf_counter() - inicio

    tiempos = [t for t, _ in resultados]
    errores = [e for _, e in resultados if e]
    tiempos.sort()

    def percentil(valor: float) -> float:
        if not tiempos:
            return 0.0
        indice = min(len(tiempos) - 1, int(len(tiempos) * valor))
        return tiempos[indice]

    print(f"clientes: {args.clientes} | mensajes: {len(resultados)}")
    print(f"tiempo total: {total:.1f} s")
    print(f"p50: {statistics.median(tiempos):.0f} ms")
    print(f"p95: {percentil(0.95):.0f} ms")
    print(f"máxima: {max(tiempos):.0f} ms")
    print(f"errores: {len(errores)}")
    for error in errores[:5]:
        print("  ", error)
    return 0 if not errores else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
