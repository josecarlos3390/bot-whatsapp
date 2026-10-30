"""Asistente para crear reglas, ocasiones y artículos conversando.

El usuario escribe lo que quiere en lenguaje natural. El asistente devuelve
un **borrador** con los campos que entendió, las preguntas que faltan y un
resumen para confirmar. Nunca escribe en la base: la creación la hace la
pantalla cuando la persona confirma.
"""

from __future__ import annotations

import json
import logging
import re

from ..config import settings

logger = logging.getLogger(__name__)

# Plantillas por tipo: campos obligatorios y cómo se explican.
TIPOS: dict[str, dict] = {
    "regla": {
        "campos": {
            "name": "nombre corto de la regla",
            "area": "área (ecommerce, marketing, operaciones, calidad)",
            "rule_type": (
                "tipo: brand_priority, promotion_priority, "
                "required_questions, response_rule, return_flow"
            ),
            "condition": "cuándo aplica (categoría, intención)",
            "action": "qué hace (marca, descuento mínimo, instrucción, preguntas)",
            "priority": "prioridad 0-100 (más alto gana)",
            "status": "published o draft",
        },
        "obligatorios": ("name", "area", "rule_type", "condition", "action", "priority"),
        "ejemplo": (
            "Si la regla es de marca, action debe ser {\"brand\": \"ELECTROLUX\"}. "
            "Si es de promociones, action {\"min_discount\": 20}. "
            "condition {\"category\": \"cocinas\"}."
        ),
    },
    "ocasion": {
        "campos": {
            "name": "nombre visible de la ocasión",
            "slug": "identificador corto (sin espacios)",
            "aliases": "cómo la llama la gente",
            "direct": "productos o rubros que se ofrecen",
            "priority": "prioridad 0-100",
            "status": "published o draft",
        },
        "obligatorios": ("name", "direct", "priority"),
        "ejemplo": "Para halloween: direct [\"vela\", \"guirnalda\"].",
    },
    "conocimiento": {
        "campos": {
            "title": "título del artículo",
            "status": "published o draft",
            "tags": "palabras con las que el cliente lo dispara",
            "content": "texto del artículo, en viñetas cortas",
        },
        "obligatorios": ("title", "tags", "content"),
        "ejemplo": "Garantía de colchones: 12 meses por falla de fábrica.",
    },
}

PROMPT = """Sos el asistente de configuración de un bot de atención.

El usuario quiere crear un elemento de tipo «{tipo}». Campos disponibles:
{campos}

Reglas:
- Devolvé SOLO JSON con esta forma:
  {{"borrador": {{...campos entendidos...}},
    "faltantes": ["campo1", "campo2"],
    "preguntas": ["pregunta para el campo1", "..."],
    "resumen": "frase que explica qué se va a crear"}}
- No inventes datos: si el usuario no dijo la prioridad, va en faltantes.
- Si ya están todos los obligatorios, faltantes y preguntas van vacías.
- El resumen debe poder leerse en voz alta para confirmar la creación.
{ejemplo}
Conversación:
{conversacion}"""


def parsear(respuesta: str, tipo: str) -> dict | None:
    """Interpreta la respuesta del modelo y valida los campos."""
    texto = (respuesta or "").strip().strip("`")
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin <= inicio:
        return None
    try:
        datos = json.loads(texto[inicio : fin + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(datos, dict):
        return None
    plantilla = TIPOS.get(tipo)
    if plantilla is None:
        return None

    borrador = datos.get("borrador")
    if not isinstance(borrador, dict):
        borrador = {}
    # Solo campos conocidos; el resto se descarta.
    limpio = {
        clave: valor
        for clave, valor in borrador.items()
        if clave in plantilla["campos"] and valor not in (None, "", [], {})
    }

    obligatorios = plantilla["obligatorios"]
    faltantes = [campo for campo in obligatorios if campo not in limpio]
    preguntas = datos.get("preguntas")
    if not isinstance(preguntas, list):
        preguntas = []
    preguntas = [str(p).strip() for p in preguntas if str(p).strip()][:6]
    # Si el modelo no preguntó por un campo faltante, se pregunta igual.
    for campo in faltantes:
        if not any(campo in pregunta.lower() for pregunta in preguntas):
            preguntas.append(
                f"¿Qué valor querés para «{campo}»? "
                f"({plantilla['campos'][campo]})"
            )
    resumen = str(datos.get("resumen") or "").strip()[:400]
    return {
        "tipo": tipo,
        "borrador": limpio,
        "faltantes": faltantes,
        "preguntas": preguntas,
        "resumen": resumen,
        "listo": not faltantes,
    }


async def conversar(agent, tipo: str, mensajes: list[dict]) -> dict | None:
    """Pide al modelo el borrador a partir de la conversación."""
    if tipo not in TIPOS:
        return None
    plantilla = TIPOS[tipo]
    campos = "\n".join(
        f"- {campo}: {ayuda}" for campo, ayuda in plantilla["campos"].items()
    )
    conversacion = "\n".join(
        f"{'Usuario' if m.get('role') != 'assistant' else 'Asistente'}: "
        f"{str(m.get('content') or '')[:600]}"
        for m in mensajes[-8:]
    )
    prompt = PROMPT.format(
        tipo=tipo,
        campos=campos,
        ejemplo=plantilla["ejemplo"],
        conversacion=conversacion,
    )
    try:
        respuesta = await agent._llm().chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=700,
            extra_body={"thinking": {"type": "disabled"}},
        )
        contenido = respuesta.choices[0].message.content or ""
    except Exception:  # noqa: BLE001 - el asistente no debe romper la consola
        logger.debug("No se pudo conversar con el asistente", exc_info=True)
        return None
    return parsear(contenido, tipo)


def slug(texto: str) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", (texto or "").lower())
    simple = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", simple).strip("-")[:60]
