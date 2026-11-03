"""Carrito espejo en VTEX: el cliente termina la compra en la tienda.

La idea: el bot arma el carrito y lo replica en un `orderForm` de VTEX. Con
el id de ese carrito se le da al cliente un link para pagar, y el recordatorio
de WhatsApp puede apuntar al mismo link.

Requiere credenciales de la tienda (appKey/appToken). Sin ellas el servicio
queda apagado y el bot sigue trabajando con su carrito local.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..models import Cart, CartItem

logger = logging.getLogger(__name__)


class VtexCartError(RuntimeError):
    """Falla al hablar con el carrito de VTEX."""


def disponible() -> bool:
    """¿Está configurado el carrito de VTEX?

    Por el integrador alcanza con la llave del PaaS; directo hacen falta las
    credenciales de la tienda.
    """
    if not settings.vtex_cart_enabled:
        return False
    if settings.vtex_cart_via == "paas":
        return bool(settings.sap_paas_url and settings.sap_paas_api_key)
    return bool(
        settings.vtex_account
        and settings.vtex_app_key
        and settings.vtex_app_token
    )


def _base() -> str:
    if _por_paas():
        return settings.sap_paas_url.rstrip("/")
    entorno = settings.vtex_environment or "vtexcommercestable"
    return f"https://{settings.vtex_account}.{entorno}.com.br"


def _por_paas() -> bool:
    return settings.vtex_cart_via == "paas"


def _cabeceras() -> dict[str, str]:
    if _por_paas():
        return {
            "X-API-Key": settings.sap_paas_api_key,
            "X-Tenant": settings.sap_paas_tenant,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    return {
        "X-VTEX-API-AppKey": settings.vtex_app_key,
        "X-VTEX-API-AppToken": settings.vtex_app_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def url_para_cliente(order_form_id: str) -> str:
    """Link que abre el cliente para pagar."""
    host = (settings.vtex_checkout_host or _base()).rstrip("/")
    return f"{host}/checkout/#/orderform/{order_form_id}"


async def _pedir(
    metodo: str, ruta: str, json: dict | None = None
) -> dict:
    async with httpx.AsyncClient(timeout=12) as cliente:
        respuesta = await cliente.request(
            metodo, f"{_base()}{ruta}", headers=_cabeceras(), json=json
        )
    if respuesta.status_code >= 400:
        raise VtexCartError(
            f"VTEX {respuesta.status_code}: {respuesta.text[:200]}"
        )
    datos = respuesta.json()
    return datos if isinstance(datos, dict) else {}


async def crear_carrito() -> str:
    """Crea un carrito anónimo y devuelve su id."""
    if _por_paas():
        datos = await _pedir(
            "POST",
            "/api/vtex/cart",
            json={
                "sales_channel": settings.vtex_sales_channel,
                "affiliate_id": settings.vtex_affiliate_id or None,
            },
        )
    else:
        params = f"?sc={settings.vtex_sales_channel}"
        if settings.vtex_affiliate_id:
            params += f"&affiliateId={settings.vtex_affiliate_id}"
        datos = await _pedir("POST", f"/api/checkout/pub/orderForm{params}")
    order_form_id = str(datos.get("orderFormId") or "")
    if not order_form_id:
        raise VtexCartError("VTEX no devolvió orderFormId")
    return order_form_id


async def agregar_items(
    order_form_id: str, items: list[dict], seller: str = "1"
) -> dict:
    """Suma o actualiza artículos en el carrito de VTEX."""
    cuerpo = {
        "items": [
            {
                "id": str(item["sku"]),
                "quantity": int(item["quantity"]),
                "seller": seller,
            }
            for item in items
            if int(item.get("quantity") or 0) > 0
        ]
    }
    if not cuerpo["items"]:
        return {}
    if _por_paas():
        return await _pedir(
            "POST",
            f"/api/vtex/cart/{order_form_id}/items",
            json={"items": cuerpo["items"]},
        )
    return await _pedir(
        "POST",
        f"/api/checkout/pub/orderForm/{order_form_id}/items"
        f"?sc={settings.vtex_sales_channel}",
        json=cuerpo,
    )


async def _items_del_carrito(carrito: Cart) -> list[dict]:
    return [
        {"sku": item.sku, "quantity": int(item.quantity or 0)}
        for item in carrito.items
    ]


async def sincronizar(carrito: Cart) -> Cart:
    """Deja el carrito de VTEX igual al local. No rompe si falla."""
    if not disponible():
        return carrito
    if not carrito.items:
        return carrito
    try:
        if not carrito.vtex_order_form_id:
            carrito.vtex_order_form_id = await crear_carrito()
        await agregar_items(
            carrito.vtex_order_form_id, await _items_del_carrito(carrito)
        )
        carrito.vtex_cart_url = url_para_cliente(carrito.vtex_order_form_id)
        from ..models import utcnow

        carrito.vtex_synced_at = utcnow()
    except Exception:  # noqa: BLE001 - el carrito local sigue siendo válido
        logger.warning("No se pudo sincronizar el carrito con VTEX", exc_info=True)
    return carrito


def link_para_pagar(carrito: Cart) -> str:
    """Link de pago si el carrito está replicado; si no, cadena vacía."""
    if carrito.vtex_cart_url:
        return carrito.vtex_cart_url
    if carrito.vtex_order_form_id:
        return url_para_cliente(carrito.vtex_order_form_id)
    return ""
