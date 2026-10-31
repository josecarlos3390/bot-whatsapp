"""Cotizar el envío: preguntar la ciudad y responder la tarifa real.

El cliente pregunta «¿cuánto sale el envío?» y el bot, en vez de copiar toda
la tabla, pregunta a dónde y responde un solo dato.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

RUTA = Path("knowledge") / "tarifas-envio.json"
_CACHE: tuple[float, dict] = (0.0, {})


def _cargar() -> dict:
    global _CACHE
    try:
        sello = RUTA.stat().st_mtime
    except OSError:
        return {}
    if _CACHE[0] == sello and _CACHE[1]:
        return _CACHE[1]
    try:
        datos = json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("No se pudieron leer las tarifas de envío", exc_info=True)
        return {}
    _CACHE = (sello, datos)
    return datos


def zonas() -> list[dict]:
    return _cargar().get("zonas") or []


def gratis_desde() -> float:
    try:
        return float(_cargar().get("gratis_desde") or 0)
    except (TypeError, ValueError):
        return 0.0


def retiro() -> str:
    return _cargar().get("retiro") or "Retiro en tienda: sin costo."


def _formato(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")


def buscar(texto: str) -> dict | None:
    """Zona que mencionó el cliente."""
    valor = (texto or "").strip().lower()
    if not valor:
        return None
    for zona in zonas():
        for alias in zona.get("alias") or []:
            if alias in valor:
                return zona
    return None


def por_clave(clave: str) -> dict | None:
    for zona in zonas():
        if zona.get("clave") == clave:
            return zona
    return None


def cotizar(zona: dict) -> str:
    """Frase con el costo y el plazo de esa zona."""
    costo = float(zona.get("costo") or 0)
    plazo = zona.get("plazo") or "24 a 48 horas"
    nota = zona.get("nota") or ""
    texto = (
        f"*{zona.get('etiqueta')}*: envío Bs {_formato(costo)} · "
        f"llega en {plazo}."
    )
    if nota:
        texto += f" {nota}"
    libre = gratis_desde()
    if libre:
        texto += f"\nEnvío sin costo en compras desde Bs {_formato(libre)}."
    texto += f"\n{retiro()}"
    return texto


def pregunta() -> str:
    return (
        "¿A dónde lo enviamos? Así te paso el costo exacto 👇"
    )


def opciones() -> list[dict]:
    """Ciudades para elegir, como lista (WhatsApp permite 3 botones)."""
    salida = [
        {
            "id": f"envio:{zona['clave']}",
            "title": (zona.get("etiqueta") or "")[:24],
            "description": f"Bs {_formato(float(zona.get('costo') or 0))}",
        }
        for zona in zonas()
    ]
    return salida


def actualizado() -> str:
    valor = _cargar().get("actualizado") or ""
    if not valor:
        return ""
    try:
        fecha = datetime.fromisoformat(valor).replace(tzinfo=timezone.utc)
    except ValueError:
        return valor
    return fecha.strftime("%d/%m/%Y")
