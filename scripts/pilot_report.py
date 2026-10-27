"""Informe diario del piloto: qué pasó con los clientes reales.

Responde tres preguntas: cuánta gente escribió, qué resolvió el bot y qué
quedó pendiente. Se puede correr a mano o dejarlo programado.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    Handoff,
    Message,
    QueryLearning,
)

ROOT = Path(__file__).resolve().parent.parent
SALIDA = ROOT / "logs"

SIN_RESULTADO = (
    "no encontré productos",
    "no tengo eso exacto",
    "no tengo productos",
    "no encontré",
)


def pendientes_de(mensajes) -> Counter:
    """Mensajes del cliente que el bot no pudo resolver."""
    pendientes: list[str] = []
    anterior_entrante = None
    for mensaje in mensajes:
        if getattr(mensaje, "direction", "") == "in":
            anterior_entrante = getattr(mensaje, "text", "") or ""
            continue
        texto = (getattr(mensaje, "text", "") or "").lower()
        if anterior_entrante and any(marca in texto for marca in SIN_RESULTADO):
            pendientes.append(anterior_entrante.strip()[:90])
    return Counter(pendientes)


def _resumen(datos: dict, horas: int) -> str:
    lineas = [
        f"# Piloto · últimas {horas} h",
        "",
        f"Generado: {datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M}",
        "",
        "## Actividad",
        "",
        f"- Conversaciones con mensajes: **{datos['conversaciones']}**",
        f"- Mensajes recibidos: **{datos['entrantes']}**",
        f"- Mensajes enviados: **{datos['salientes']}**",
        f"- Clientes nuevos: **{datos['contactos_nuevos']}**",
        "",
        "## Atención",
        "",
        f"- Casos derivados: **{datos['derivados']}**",
        f"- Resueltos: **{datos['resueltos']}**",
        f"- En cola ahora: **{datos['en_cola']}**",
        f"- Escalados por demora: **{datos['escalados']}**",
        f"- Respuestas descartadas por incoherencia: **{datos['incoherentes']}**",
        "",
        "## Lo que el bot no resolvió",
        "",
    ]
    if datos["sin_resultado"]:
        for texto, veces in datos["sin_resultado"]:
            lineas.append(f"- {veces}× · {texto}")
    else:
        lineas.append("- Nada pendiente.")
    lineas += ["", "## Aprendizaje pendiente de revisar", ""]
    if datos["aprendizaje"]:
        for texto in datos["aprendizaje"]:
            lineas.append(f"- {texto}")
    else:
        lineas.append("- Nada pendiente.")
    lineas += ["", "## Cómo leerlo", ""]
    lineas.append(
        f"- Si 'sin resolver' supera el 20 % de los mensajes "
        f"({round(datos['entrantes'] * 0.2) or 1}), revisar catálogo y textos."
    )
    lineas.append(
        "- Si 'incoherentes' sube, hay un texto fijo disparando en contexto "
        "equivocado."
    )
    lineas.append(
        "- Si 'en cola' no baja, faltan asesores en línea o el tope es bajo."
    )
    return "\n".join(lineas) + "\n"


async def generar(horas: int = 24) -> tuple[str, dict]:
    desde = datetime.now(timezone.utc) - timedelta(hours=max(horas, 1))
    async with SessionLocal() as session:
        entrantes = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.created_at >= desde, Message.direction == "in")
        )
        salientes = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.created_at >= desde, Message.direction == "out")
        )
        conversaciones = await session.scalar(
            select(func.count(func.distinct(Message.conversation_id))).where(
                Message.created_at >= desde
            )
        )
        contactos_nuevos = await session.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.created_at >= desde)
        )
        derivados = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.created_at >= desde)
        )
        resueltos = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.resolved_at >= desde)
        )
        en_cola = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.status == "queued")
        )
        escalados = await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.created_at >= desde, Handoff.escalated_at.is_not(None))
        )

        mensajes = (
            await session.scalars(
                select(Message)
                .where(Message.created_at >= desde)
                .order_by(Message.created_at)
            )
        ).all()

        sin_resultado = pendientes_de(mensajes).most_common(8)

        aprendizaje = (
            await session.scalars(
                select(QueryLearning)
                .where(QueryLearning.status == "pending")
                .order_by(QueryLearning.updated_at.desc())
                .limit(8)
            )
        ).all()
        aprendizaje_txt = [
            f"{fila.term} → {fila.query or '(sin consulta)'}" for fila in aprendizaje
        ]

    incoherentes = 0
    for ruta in SALIDA.glob("*.log"):
        try:
            with ruta.open("r", encoding="utf-8", errors="ignore") as handle:
                for linea in handle:
                    if (
                        "incoherencia" in linea.lower()
                        and "bloqueada" in linea.lower()
                    ):
                        incoherentes += 1
        except OSError:
            continue

    datos = {
        "conversaciones": conversaciones or 0,
        "entrantes": entrantes or 0,
        "salientes": salientes or 0,
        "contactos_nuevos": contactos_nuevos or 0,
        "derivados": derivados or 0,
        "resueltos": resueltos or 0,
        "en_cola": en_cola or 0,
        "escalados": escalados or 0,
        "sin_resultado": sin_resultado,
        "aprendizaje": aprendizaje_txt,
        "incoherentes": incoherentes,
    }
    return _resumen(datos, horas), datos


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--horas", type=int, default=24)
    parser.add_argument("--salida", type=str, default="")
    args = parser.parse_args()

    texto, datos = await generar(args.horas)
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = Path(args.salida) if args.salida else (
        SALIDA / f"piloto-{datetime.now():%Y-%m-%d}.md"
    )
    destino.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Guardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
