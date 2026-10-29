"""Lectura del mensaje antes de las reglas.

Las reglas no entienden el lenguaje: «vendes focas» o «mostrame las más
elegidas» dependen de expresiones exactas. Acá se pide una lectura
estructurada (intención, producto, atributos) y con eso se decide el camino.

Se activa con NLU_FIRST=true y se mide contra el camino de reglas.
"""

from __future__ import annotations

import logging

from ..config import settings
from . import catalog, understanding

logger = logging.getLogger(__name__)


def consulta(lectura: dict | None) -> str:
    """Texto de búsqueda a partir de la lectura."""
    if not lectura:
        return ""
    partes = [lectura.get("producto") or ""]
    atributos = lectura.get("atributos") or []
    if isinstance(atributos, str):
        atributos = [atributos]
    partes.extend(str(a) for a in atributos if a)
    return " ".join(p for p in partes if p).strip()


async def leer(agent, texto: str) -> dict | None:
    """Lectura estructurada del mensaje, si la IA está disponible."""
    if not settings.deepseek_api_key:
        return None
    try:
        lectura = await understanding.parse(texto)
    except Exception:  # noqa: BLE001 - sin lectura se sigue con reglas
        logger.debug("No se pudo leer el mensaje", exc_info=True)
        return None
    if not lectura:
        return None
    agent._trace(
        f"NLU: {lectura.get('intencion')} · {lectura.get('producto')}"
    )
    return lectura


def es_busqueda(lectura: dict | None) -> bool:
    """¿La lectura dice que el cliente quiere ver productos?"""
    if not lectura:
        return False
    intencion = str(lectura.get("intencion") or "")
    producto = str(lectura.get("producto") or "")
    if not producto:
        return False
    if intencion in {"producto", "precio", "comparacion"}:
        return True
    # «hola, tenés taladros»: el saludo no impide mostrar el producto.
    return intencion in {"saludo", "otro"} and bool(
        catalog.primary_term(producto)
    )
