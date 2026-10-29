"""Comparar el camino de reglas con la lectura por IA (NLU primero).

Corre los mismos guiones dos veces y compara fallos y latencia.

Uso:
    python -m scripts.comparar_nlu
"""

from __future__ import annotations

import asyncio
import statistics
import time

from sqlalchemy import delete, select

from app.agent import Agent
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    ConversationFlow,
    ConversationGuard,
    ConversationState,
    Handoff,
    Message,
)
from scripts.auditoria_dialogos import CASOS, evaluar


def _casos(generados: bool) -> list[dict]:
    import sys

    if "--mals" in sys.argv:
        from scripts.casos_mals import CASOS_MALS

        return list(CASOS_MALS)
    todos = list(CASOS)
    if generados:
        import json
        from pathlib import Path as _Path

        ruta = _Path("scripts") / "guiones_generados.json"
        if ruta.exists():
            todos.extend(json.loads(ruta.read_text(encoding="utf-8")).get("casos") or [])
    return todos


async def _correr(modo_nlu: bool, casos: list[dict]) -> tuple[int, float]:
    settings.nlu_first = modo_nlu
    fallos = 0
    tiempos: list[float] = []
    async with SessionLocal() as session:
        for caso in casos:
            sufijo = f"nlu{int(modo_nlu)}{abs(hash(caso['id'])) % 10000}"
            contacto = Contact(
                wa_id=sufijo, phone_e164=f"+0{sufijo[:10]}", name="NLU"
            )
            session.add(contacto)
            await session.flush()
            conversacion = Conversation(contact_id=contacto.id)
            session.add(conversacion)
            await session.commit()

            salidas: list[str] = []
            for mensaje in caso["mensajes"]:
                agente = Agent()
                inicio = time.perf_counter()
                respuesta = await agente.handle(session, contacto, mensaje)
                respuesta = await agente.postprocess(
                    session, contacto, mensaje, respuesta
                )
                tiempos.append((time.perf_counter() - inicio) * 1000)
                salidas.append(" ".join(m.text or "" for m in respuesta.messages))
            ok, _ = evaluar(salidas, caso["espera"])
            if not ok:
                fallos += 1

            await session.execute(
                delete(Message).where(
                    Message.conversation_id == conversacion.id
                )
            )
            await session.execute(
                delete(Handoff).where(Handoff.conversation_id == conversacion.id)
            )
            await session.execute(
                delete(ConversationFlow).where(
                    ConversationFlow.conversation_id == conversacion.id
                )
            )
            await session.execute(
                delete(ConversationState).where(
                    ConversationState.conversation_id == conversacion.id
                )
            )
            await session.execute(
                delete(ConversationGuard).where(
                    ConversationGuard.conversation_id == conversacion.id
                )
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversacion.id)
            )
            await session.execute(delete(Contact).where(Contact.id == contacto.id))
            await session.commit()
    mediana = statistics.median(tiempos) if tiempos else 0.0
    return fallos, mediana


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--generados", action="store_true")
    parser.add_argument("--mals", action="store_true")
    args = parser.parse_args()
    casos = _casos(args.generados)
    print(f"casos: {len(casos)}")
    reglas_fallos, reglas_ms = await _correr(False, casos)
    nlu_fallos, nlu_ms = await _correr(True, casos)
    settings.nlu_first = False

    print(f"\nreglas      : fallos {reglas_fallos} | mediana {reglas_ms:.0f} ms")
    print(f"IA primero  : fallos {nlu_fallos} | mediana {nlu_ms:.0f} ms")
    print()
    if nlu_fallos < reglas_fallos:
        print("La lectura por IA acierta más: conviene activarla.")
    elif nlu_fallos > reglas_fallos:
        print("Las reglas aciertan más: no conviene activarla todavía.")
    elif nlu_ms < reglas_ms * 0.9:
        print("Aciertan igual y la lectura por IA es más rápida: conviene activarla.")
    else:
        print("Aciertan igual y sin ventaja de velocidad: esperar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
