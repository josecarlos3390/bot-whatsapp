"""Agrupar mensajes seguidos: una foto y un «hola» son un solo turno.

Cuando el cliente manda varias cosas en pocos segundos, contestar cada una por
separado se ve raro (saludo + análisis de la foto). Acá se espera un momento
corto y se procesan juntas.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Cuánto se espera para juntar mensajes seguidos.
ESPERA_MS = 1600

# Los botones y las acciones tienen que responderse al toque.
_PREFIJOS_ACCION = (
    "product:",
    "cat:",
    "type:",
    "see:",
    "add:",
    "qty:",
    "remove:",
    "refine:",
    "uso:",
    "price:",
    "find:",
    "doc:",
    "idea:",
    "more",
    "filter",
    "catalog",
    "cart",
    "estado",
    "human",
    "asesor",
    "search",
)

_pendientes: dict[str, asyncio.Task] = {}
_buffer: dict[str, dict] = {}


def es_accion(texto: str) -> bool:
    """¿Es un botón o un comando que necesita respuesta inmediata?"""
    valor = (texto or "").strip().lower()
    return any(valor == prefijo or valor.startswith(prefijo) for prefijo in _PREFIJOS_ACCION)


def _unir(previo: dict, nuevo: dict) -> dict:
    """Combina dos mensajes del mismo turno."""
    textos = [
        (previo.get("text") or "").strip(),
        (nuevo.get("text") or "").strip(),
    ]
    limpios: list[str] = []
    for texto in textos:
        # Las marcas tipo "[image]" no aportan como texto.
        if texto and texto.strip("[]").lower() not in {
            "",
            "image",
            "video",
            "document",
            "audio",
            "ubicación",
        }:
            if texto not in limpios:
                limpios.append(texto)
    combinado = "\n".join(limpios)
    media = nuevo.get("media") or previo.get("media")
    if not combinado and not media:
        combinado = nuevo.get("text") or previo.get("text") or ""
    return {
        **nuevo,
        "text": combinado,
        "media": media,
        # El id del último mensaje manda: es el que se marca como leído.
        "wa_message_id": nuevo.get("wa_message_id") or previo.get("wa_message_id"),
    }


async def agrupar(
    wa_id: str,
    item: dict,
    procesar,
    *,
    espera_ms: int = ESPERA_MS,
) -> None:
    """Acumula el mensaje y procesa el grupo cuando el cliente se calla."""
    if es_accion(item.get("text") or ""):
        anterior = _pendientes.pop(wa_id, None)
        if anterior is not None and not anterior.done():
            anterior.cancel()
        pendiente = _buffer.pop(wa_id, None)
        if pendiente is not None:
            await procesar(pendiente)
        await procesar(item)
        return

    acumulado = _buffer.get(wa_id)
    _buffer[wa_id] = _unir(acumulado, item) if acumulado else item

    if espera_ms <= 0:
        # Sin espera (tests o modo síncrono): se procesa en el acto.
        pendiente = _buffer.pop(wa_id, None)
        if pendiente is not None:
            await procesar(pendiente)
        return

    anterior = _pendientes.pop(wa_id, None)
    if anterior is not None and not anterior.done():
        anterior.cancel()

    async def _esperar() -> None:
        try:
            await asyncio.sleep(max(espera_ms, 0) / 1000)
        except asyncio.CancelledError:
            return
        pendiente = _buffer.pop(wa_id, None)
        if pendiente is None:
            return
        try:
            await procesar(pendiente)
        except Exception:  # noqa: BLE001 - Meta reintenta
            logger.exception("No se pudo procesar el grupo de %s", wa_id)

    _pendientes[wa_id] = asyncio.create_task(_esperar())
