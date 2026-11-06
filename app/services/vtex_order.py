"""Enviar el pedido a VTEX con los datos de facturación y entrega.

El pago se confirma en el bot; después hay que crear la venta en VTEX con los
datos del formulario. Mientras el PaaS no exponga el endpoint, se simula y se
deja el payload registrado para no perderlo.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Cart, Contact
from . import cart as cart_service

logger = logging.getLogger(__name__)


def _lineas(resumen: dict) -> list[dict]:
    return [
        {
            "sku": linea["sku"],
            "quantity": linea["quantity"],
            "price": str(linea["unit_price"]),
        }
        for linea in resumen.get("lines") or []
    ]


async def crear_pedido(
    session: AsyncSession,
    contact: Contact,
    cart: Cart,
    datos: dict,
) -> dict:
    """Crea el pedido en VTEX (o lo simula si no hay endpoint)."""
    resumen = await cart_service.summary(session, cart)
    payload = {
        "contact": {
            "wa_id": contact.wa_id,
            "name": contact.name,
            "tax_id": datos.get("documento") or contact.tax_id,
        },
        "billing": {
            "name": datos.get("nombre_factura") or contact.name,
            "document": datos.get("documento") or "",
        },
        "shipping": {
            "method": datos.get("metodo") or "domicilio",
            "name": datos.get("nombre_recibe") or "",
            "address": datos.get("direccion") or "",
            "reference": datos.get("referencia") or "",
        },
        "items": _lineas(resumen),
        "total": str(Decimal(resumen.get("total") or 0)),
        "currency": resumen.get("currency") or "BOB",
    }

    ruta = (getattr(settings, "vtex_order_path", "") or "").strip()
    if not ruta:
        logger.info("Pedido simulado (sin VTEX_ORDER_PATH): %s", payload)
        return {
            "ok": True,
            "simulado": True,
            "numero": None,
            "mensaje": (
                "El pedido quedó registrado. Estamos generando la venta en "
                "el sistema."
            ),
        }

    url = f"{settings.sap_paas_url.rstrip('/')}{ruta}"
    cabeceras = {
        "X-API-Key": settings.sap_paas_api_key,
        "X-Tenant": settings.sap_paas_tenant,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as cliente:
            respuesta = await cliente.post(url, json=payload, headers=cabeceras)
        if respuesta.status_code >= 400:
            logger.warning(
                "VTEX rechazó el pedido (%s): %s",
                respuesta.status_code,
                respuesta.text[:300],
            )
            return {
                "ok": False,
                "numero": None,
                "mensaje": (
                    "No pudimos generar la venta en el sistema. Te paso con "
                    "un asesor para no perder tu pedido."
                ),
            }
        datos_respuesta = respuesta.json() or {}
        return {
            "ok": True,
            "simulado": False,
            "numero": datos_respuesta.get("orderId")
            or datos_respuesta.get("order_id"),
            "mensaje": "Tu pedido quedó generado.",
        }
    except Exception:  # noqa: BLE001 - el pedido no se pierde
        logger.exception("Error creando el pedido en VTEX")
        return {
            "ok": False,
            "numero": None,
            "mensaje": (
                "No pudimos generar la venta en el sistema. Te paso con un "
                "asesor para no perder tu pedido."
            ),
        }
