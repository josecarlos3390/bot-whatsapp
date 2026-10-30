"""Consumo de la API: tokens y costo estimado por tipo de uso.

Cada llamada al modelo informa `usage`. Acá se anota con la operación
(conversación, imagen, relacionados, pregunta de uso) para saber en qué se
va el consumo y cuánto cuesta.

Los precios son configurables: cambian con el proveedor.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

RUTA = Path(".tools") / "consumo-ia.jsonl"
MAX_LINEAS = 20000

# Operaciones que se miden.
OPERACIONES = (
    "conversacion",
    "imagen",
    "relacionados",
    "pregunta_uso",
    "lectura",
    "fuzz",
    "otro",
)


def _tokens(usage) -> tuple[int, int, int]:
    """(prompt, completion, cache) desde el objeto usage del proveedor."""
    if usage is None:
        return 0, 0, 0
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    detalles = getattr(usage, "prompt_tokens_details", None)
    cache = 0
    if detalles is not None:
        cache = int(getattr(detalles, "cached_tokens", 0) or 0)
    return prompt, completion, cache


def costo(prompt: int, completion: int) -> float:
    """Costo estimado en dólares según los precios configurados."""
    entrada = getattr(settings, "deepseek_precio_entrada", 0.0) or 0.0
    salida = getattr(settings, "deepseek_precio_salida", 0.0) or 0.0
    return round(
        prompt / 1_000_000 * entrada + completion / 1_000_000 * salida, 6
    )


def registrar(
    operacion: str,
    usage=None,
    *,
    modelo: str = "",
    contacto_id: str = "",
) -> dict | None:
    """Anota una llamada al modelo. Nunca interrumpe la respuesta."""
    try:
        prompt, completion, cache = _tokens(usage)
        if not prompt and not completion:
            return None
        fila = {
            "at": datetime.now(timezone.utc).isoformat(),
            "operacion": operacion if operacion in OPERACIONES else "otro",
            "modelo": modelo or settings.deepseek_model,
            "prompt": prompt,
            "completion": completion,
            "cache": cache,
            "costo_usd": costo(prompt, completion),
            "contacto": contacto_id,
        }
        RUTA.parent.mkdir(parents=True, exist_ok=True)
        with RUTA.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(fila) + "\n")
        _recortar()
        return fila
    except Exception:  # noqa: BLE001 - la métrica no frena la respuesta
        logger.debug("No se pudo registrar el consumo", exc_info=True)
        return None


def _recortar() -> None:
    """Deja las últimas N líneas para que el archivo no crezca sin límite."""
    try:
        if not RUTA.exists() or RUTA.stat().st_size < 4_000_000:
            return
        lineas = RUTA.read_text(encoding="utf-8").splitlines()
        if len(lineas) > MAX_LINEAS:
            RUTA.write_text(
                "\n".join(lineas[-MAX_LINEAS:]) + "\n", encoding="utf-8"
            )
    except OSError:
        logger.debug("No se pudo recortar el consumo", exc_info=True)


def leer() -> list[dict]:
    filas: list[dict] = []
    if not RUTA.exists():
        return filas
    try:
        with RUTA.open(encoding="utf-8") as archivo:
            for linea in archivo:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    filas.append(json.loads(linea))
                except ValueError:
                    continue
    except OSError:
        return []
    return filas


def resumen(dias: int = 7) -> dict:
    """Totales por operación y por día, con costo estimado."""
    from datetime import timedelta

    desde = datetime.now(timezone.utc) - timedelta(days=max(dias, 1))
    filas = []
    for fila in leer():
        try:
            cuando = datetime.fromisoformat(fila.get("at", ""))
        except ValueError:
            continue
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
        if cuando >= desde:
            filas.append(fila)

    por_operacion: dict[str, dict] = {}
    por_dia: dict[str, dict] = {}
    for fila in filas:
        operacion = fila.get("operacion") or "otro"
        datos = por_operacion.setdefault(
            operacion, {"llamadas": 0, "prompt": 0, "completion": 0, "costo": 0.0}
        )
        datos["llamadas"] += 1
        datos["prompt"] += int(fila.get("prompt") or 0)
        datos["completion"] += int(fila.get("completion") or 0)
        datos["costo"] = round(datos["costo"] + float(fila.get("costo_usd") or 0), 4)

        dia = str(fila.get("at", ""))[:10]
        deldia = por_dia.setdefault(dia, {"llamadas": 0, "costo": 0.0})
        deldia["llamadas"] += 1
        deldia["costo"] = round(deldia["costo"] + float(fila.get("costo_usd") or 0), 4)

    total_costo = round(sum(f.get("costo", 0) for f in por_operacion.values()), 4)
    total_prompt = sum(f.get("prompt", 0) for f in por_operacion.values())
    total_completion = sum(f.get("completion", 0) for f in por_operacion.values())
    return {
        "dias": dias,
        "llamadas": len(filas),
        "prompt": total_prompt,
        "completion": total_completion,
        "costo_usd": total_costo,
        "operaciones": dict(
            sorted(
                por_operacion.items(),
                key=lambda par: par[1]["llamadas"],
                reverse=True,
            )
        ),
        "dias_detalle": dict(sorted(por_dia.items())),
    }
