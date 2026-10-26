"""Reglas de ejemplo: preguntas obligatorias, devolución e indicación de respuesta."""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AreaRule
from app.services import area_rules


async def crear_si_falta(session, nombre: str, **datos):
    existente = await session.scalar(
        select(AreaRule).where(AreaRule.name == nombre)
    )
    if existente is not None:
        print(f"ya existe: {nombre}")
        return existente
    regla = await area_rules.create_rule(
        session, changed_by="asistente", name=nombre, **datos
    )
    print(f"creada: {regla.name} ({regla.id[:8]}) {regla.rule_type} prio {regla.priority}")
    return regla


async def retirar(session, nombre: str) -> None:
    """Pasa a borrador las reglas de prueba que chocan con los ejemplos."""
    regla = await session.scalar(select(AreaRule).where(AreaRule.name == nombre))
    if regla is None or regla.status == "draft":
        return
    await area_rules.set_status(
        session, regla, status="draft", changed_by="asistente"
    )
    print(f"a borrador: {nombre}")


async def main() -> None:
    async with SessionLocal() as session:
        await crear_si_falta(
            session,
            "Ejemplo: preguntas antes de vender una heladera",
            area="ecommerce",
            rule_type="required_questions",
            condition={"category": "Heladeras"},
            action={
                "questions": [
                    {"text": "¿Cuántos litros necesitás?", "key": "litros"},
                    {
                        "text": "¿Tenés el espacio disponible (ancho y alto)?",
                        "key": "espacio",
                    },
                ]
            },
            priority=50,
            status="published",
        )

        await crear_si_falta(
            session,
            "Ejemplo: devolución de una licuadora",
            area="calidad",
            rule_type="return_flow",
            condition={"intent": "devolucion"},
            action={
                "questions": [
                    {"text": "¿Cuándo la compraste?", "key": "fecha"},
                    {
                        "text": "¿Está sin uso y con su empaque?",
                        "key": "estado",
                        "require_yes": True,
                    },
                    {
                        "text": "¿Tenés la factura o el número de pedido?",
                        "key": "factura",
                    },
                ]
            },
            priority=60,
            status="published",
        )

        await crear_si_falta(
            session,
            "Ejemplo: indicación para envíos y demoras",
            area="operaciones",
            rule_type="response_rule",
            condition={"category": "envíos"},
            action={
                "instruction": (
                    "Para envíos y demoras: informar entrega en 24 a 48 horas "
                    "en ciudades capitales y retiro en tienda el mismo día. "
                    "Si el cliente está fuera de la cobertura, ofrecer "
                    "derivar con un asesor. No inventar costos de envío."
                )
            },
            priority=50,
            status="published",
        )

        # Las reglas "de prueba" que ya no hacen falta dejan de aplicarse.
        for nombre in (
            "Flujo de devolución de prueba",
            "Información de envíos de prueba",
            "Promociones verificadas de prueba",
        ):
            await retirar(session, nombre)


if __name__ == "__main__":
    asyncio.run(main())
