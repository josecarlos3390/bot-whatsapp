"""Búsqueda libre con VTEX Intelligent Search (a través del PaaS).

VTEX aplica los sinónimos configurados en la tienda: «fumigador» encuentra
pulverizadores y «bebote» encuentra muñecas, sin replicar los 147 sinónimos en
la base del bot.

Se usa **solo para búsquedas libres**. Los filtros, las comparaciones y los
precios siguen saliendo del catálogo local, como recomendó el equipo del PaaS.

Si el endpoint no está publicado (404) se deja de llamar unos minutos: el bot
sigue trabajando con su catálogo.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Si el integrador no tiene el endpoint, no se insiste en cada mensaje.
_SIN_ENDPOINT_HASTA = 0.0
_REINTENTO_SEGUNDOS = 300


def disponible() -> bool:
    if not settings.vtex_search_enabled:
        return False
    if not (settings.sap_paas_url and settings.sap_paas_api_key):
        return False
    return time.time() >= _SIN_ENDPOINT_HASTA


def _marcar_sin_endpoint() -> None:
    global _SIN_ENDPOINT_HASTA
    _SIN_ENDPOINT_HASTA = time.time() + _REINTENTO_SEGUNDOS
    logger.info(
        "La búsqueda de VTEX no está disponible; se usa el catálogo local "
        "por %s minutos",
        _REINTENTO_SEGUNDOS // 60,
    )


def olvidar() -> None:
    """Vuelve a intentar contra el integrador (para pruebas)."""
    global _SIN_ENDPOINT_HASTA
    _SIN_ENDPOINT_HASTA = 0.0


def normalizar(item: dict) -> dict:
    return {
        "sku": str(item.get("sku") or ""),
        "sku_id": str(item.get("sku_id") or ""),
        "name": str(item.get("name") or ""),
        "price": item.get("price"),
        "list_price": item.get("list_price"),
        "currency": str(item.get("currency") or "BOB"),
        "stock": item.get("stock"),
        "brand": item.get("brand"),
        "category": item.get("category"),
        "image_url": item.get("image_url"),
        "link": item.get("link"),
    }


async def buscar(consulta: str, limite: int = 8) -> list[dict]:
    """Productos según VTEX, con sinónimos. Lista vacía si no se pudo."""
    texto = (consulta or "").strip()
    if not texto or not disponible():
        return []
    url = f"{settings.sap_paas_url.rstrip('/')}/api/vtex/search"
    cabeceras = {
        "X-API-Key": settings.sap_paas_api_key,
        "X-Tenant": settings.sap_paas_tenant,
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=8) as cliente:
            respuesta = await cliente.get(
                url,
                params={"q": texto, "limit": max(1, min(int(limite), 20))},
                headers=cabeceras,
            )
    except Exception:  # noqa: BLE001 - sin red se sigue con el catálogo
        logger.debug("No se pudo consultar la búsqueda de VTEX", exc_info=True)
        return []
    if respuesta.status_code == 404:
        _marcar_sin_endpoint()
        return []
    if respuesta.status_code >= 400:
        logger.debug(
            "Búsqueda de VTEX respondió %s", respuesta.status_code
        )
        return []
    try:
        datos = respuesta.json()
    except ValueError:
        return []
    items = datos.get("items") if isinstance(datos, dict) else datos
    if not isinstance(items, list):
        return []
    return [normalizar(item) for item in items if isinstance(item, dict)]
