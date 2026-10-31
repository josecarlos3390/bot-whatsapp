"""¿Los ejemplos que vienen cargados sirven de verdad?

Revisa reglas, ocasiones y artículos de ejemplo: si están activos, si el bot
los usa y si el contenido sirve o es un marcador.

Uso:
    python -m scripts.revisar_ejemplos
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.agent import Agent
from app.db import SessionLocal
from app.models import AreaRule, Occasion
from app.services import knowledge, occasion_store, rule_policy


async def revisar_reglas(session) -> None:
    print("REGLAS")
    reglas = (
        await session.scalars(
            select(AreaRule).order_by(AreaRule.priority.desc())
        )
    ).all()
    for regla in reglas:
        condicion = regla.condition or {}
        categoria = condicion.get("category") or condicion.get("intent") or ""
        aplica = False
        if categoria:
            policy = await rule_policy.build(
                session, "consulta", category=categoria
            )
            aplica = any(item["id"] == regla.id for item in policy.rules)
        ejemplo = "ejemplo" in (regla.name or "").lower() or "prueba" in (
            regla.name or ""
        ).lower()
        print(
            f"  {regla.status:<10} {'APLICA' if aplica else 'no aplica':<10} "
            f"{regla.rule_type:<20} {regla.name[:44]:<44}"
            f"{' [EJEMPLO]' if ejemplo else ''}"
        )


async def revisar_ocasiones(session) -> None:
    print("\nOCASIONES")
    filas = await occasion_store.list_occasions(session)
    for ocasion in filas:
        resuelta = await occasion_store.resolve(session, ocasion.name)
        activa = ocasion.status == "published"
        print(
            f"  {ocasion.status:<10} {'DETECTA' if resuelta is not None else 'no detecta':<12} "
            f"{ocasion.name[:30]:<30} direct: {len(ocasion.direct or [])}"
        )


async def revisar_conocimiento(session) -> None:
    print("\nCONOCIMIENTO")
    articulos = knowledge.load_articles(force=True)
    for articulo in articulos:
        estado = articulo.status
        muestra = articulo.sample
        cuerpo = articulo.content.strip()
        # Solo los avisos de verdad, no cualquier frase con "todo".
        marcador = any(
            aviso in cuerpo.lower()
            for aviso in (
                "contenido de ejemplo",
                "valores de ejemplo",
                "reemplazar por",
                "completar antes",
                "lorem ipsum",
            )
        )
        print(
            f"  {estado:<10} {'MUESTRA' if muestra else 'real':<8} "
            f"{len(cuerpo):>5} car. {articulo.source:<20}"
            f"{' [MARCADOR]' if marcador else ''}"
        )


async def probar_respuestas(session) -> None:
    print("\nRESPUESTAS REALES")
    from app.models import Contact, Conversation

    consultas = [
        "hacen envíos a Santa Cruz?",
        "qué garantía tiene una licuadora?",
        "puedo devolver algo que no me gustó?",
    ]
    for consulta in consultas:
        contacto = Contact(
            wa_id=f"ej{abs(hash(consulta)) % 100000}",
            phone_e164="+59170000000",
            name="Ejemplo",
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
        texto = " ".join(m.text or "" for m in respuesta.messages)
        print(f"  > {consulta}")
        print(f"    {texto[:150].replace(chr(10), ' ')}")


async def main() -> int:
    async with SessionLocal() as session:
        await revisar_reglas(session)
        await revisar_ocasiones(session)
        await revisar_conocimiento(session)
        await probar_respuestas(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
