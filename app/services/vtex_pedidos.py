"""Saber si el cliente terminó la compra en VTEX.

El cliente paga en la tienda. Para enterarse, el bot consulta los pedidos
del integrador y busca el que corresponde al carrito que él armó
(`orderFormId`).

El integrador hoy devuelve la lista completa sin filtrar, así que la
búsqueda se hace acá y se cachea unos segundos para no golpear la API en
cada mensaje.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..config import settings

logger = logging.getLogger(__name__)

# Estados de VTEX traducidos para el cliente.
ESTADOS = {
    "payment-pending": "esperando el pago",
    "payment-approved": "pago aprobado",
    "window-to-cancel": "en ventana de cancelación",
    "ready-for-handling": "en preparación",
    "handling": "preparando el envío",
    "invoiced": "facturado",
    "canceled": "cancelado",
    "order-completed": "completado",
    "delivered": "entregado",
    "returned": "devuelto",
    "on-order-completed": "completado",
}

_cache: dict = {"momento": None, "pedidos": [], "segundos": 60}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def disponible() -> bool:
    return bool(settings.sap_paas_url and settings.sap_paas_api_key)


def _fresco() -> bool:
    momento = _cache["momento"]
    if momento is None:
        return False
    return (_ahora() - momento).total_seconds() < _cache["segundos"]


def olvidar() -> None:
    """Descarta la caché (útil después de un pedido nuevo)."""
    _cache["momento"] = None
    _cache["pedidos"] = []


async def _pedidos() -> list[dict]:
    if _fresco():
        return _cache["pedidos"]
    import httpx

    cabeceras = {
        "X-API-Key": settings.sap_paas_api_key,
        "X-Tenant": settings.sap_paas_tenant,
        "Accept": "application/json",
    }
    url = f"{settings.sap_paas_url.rstrip('/')}/api/vtex/orders?limit=100"
    try:
        async with httpx.AsyncClient(timeout=10) as cliente:
            respuesta = await cliente.get(url, headers=cabeceras)
        respuesta.raise_for_status()
        datos = respuesta.json()
    except Exception:  # noqa: BLE001 - sin pedidos no pasa nada
        logger.debug("No se pudieron leer los pedidos", exc_info=True)
        return []
    lista = datos.get("list") if isinstance(datos, dict) else datos
    pedidos = [p for p in (lista or []) if isinstance(p, dict)]
    _cache["pedidos"] = pedidos
    _cache["momento"] = _ahora()
    return pedidos


def estado_legible(estado: str | None) -> str:
    clave = (estado or "").strip().lower()
    return ESTADOS.get(clave, clave.replace("-", " ") or "en proceso")


def resumen(pedido: dict) -> dict:
    return {
        "order_id": str(pedido.get("orderId") or ""),
        "sequence": str(pedido.get("sequence") or ""),
        "status": str(pedido.get("status") or ""),
        "status_legible": estado_legible(pedido.get("status")),
        "total": pedido.get("totalValue"),
        "currency": pedido.get("currencyCode") or "BOB",
    }


async def del_carrito(order_form_id: str) -> dict | None:
    """Pedido generado a partir de ese carrito, si existe."""
    buscado = (order_form_id or "").strip().lower()
    if not buscado or not disponible():
        return None
    for pedido in await _pedidos():
        if str(pedido.get("orderFormId") or "").strip().lower() == buscado:
            return resumen(pedido)
    return None
