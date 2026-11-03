"""Carrito espejo en VTEX a través del integrador (PaaS).

Reglas del contrato acordado con el equipo del PaaS:

- El identificador canónico es ``order_form_id`` (se acepta también
  ``orderFormId`` durante la transición).
- Los ítems viajan con el **RefId** del catálogo (``sku``); el PaaS lo
  resuelve al id interno de VTEX.
- El link de checkout **lo devuelve el integrador**. Si viene ``null`` no se
  muestra: no se fabrica ninguna URL.
- Si VTEX rechaza un ítem (``messages``), no se ofrece el link y se avisa
  qué producto no se pudo cargar.
- El precio que manda es el de VTEX, no el local.
- Un carrito dura 24 h: antes de usarlo se consulta y, si venció, se crea
  otro.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from ..config import settings
from ..models import Cart, utcnow

logger = logging.getLogger(__name__)

TTL_HORAS = 24


class VtexCartError(RuntimeError):
    """Falla al hablar con el carrito."""


class CarritoVencido(VtexCartError):
    """El carrito ya no existe (404)."""


def disponible() -> bool:
    """¿Está configurado el carrito de VTEX?"""
    if not settings.vtex_cart_enabled:
        return False
    if _por_paas():
        return bool(settings.sap_paas_url and settings.sap_paas_api_key)
    return bool(
        settings.vtex_account
        and settings.vtex_app_key
        and settings.vtex_app_token
    )


def _por_paas() -> bool:
    return settings.vtex_cart_via == "paas"


def _base() -> str:
    if _por_paas():
        return settings.sap_paas_url.rstrip("/")
    entorno = settings.vtex_environment or "vtexcommercestable"
    return f"https://{settings.vtex_account}.{entorno}.com.br"


def _cabeceras(cart: Cart | None = None) -> dict[str, str]:
    cabeceras = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if _por_paas():
        cabeceras["X-API-Key"] = settings.sap_paas_api_key
        cabeceras["X-Tenant"] = settings.sap_paas_tenant
    else:
        cabeceras["X-VTEX-API-AppKey"] = settings.vtex_app_key
        cabeceras["X-VTEX-API-AppToken"] = settings.vtex_app_token
    if cart is not None:
        # Reintentos del mismo carrito no crean uno nuevo.
        cabeceras["Idempotency-Key"] = f"{cart.contact_id}:{cart.id}"
    return cabeceras


def _fecha(valor) -> datetime | None:
    """Fecha ISO del integrador; null o inválida cuenta como sin dato."""
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento


def _numero(valor) -> Decimal:
    try:
        return Decimal(str(valor or 0))
    except Exception:  # noqa: BLE001 - valor raro: cero
        return Decimal("0")


def normalizar(datos: dict) -> dict:
    """Deja la respuesta del integrador en un formato único."""
    order_form_id = str(
        datos.get("order_form_id") or datos.get("orderFormId") or ""
    ).strip()
    items = []
    for item in datos.get("items") or []:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "sku": str(item.get("sku") or item.get("id") or ""),
                "sku_id": str(item.get("sku_id") or ""),
                "quantity": int(item.get("quantity") or 0),
                "price": _numero(item.get("price")),
            }
        )
    mensajes = [
        {
            "code": str(mensaje.get("code") or ""),
            "text": str(mensaje.get("text") or ""),
            "status": str(mensaje.get("status") or ""),
        }
        for mensaje in datos.get("messages") or []
        if isinstance(mensaje, dict)
    ]
    return {
        "order_form_id": order_form_id,
        "checkout_url": datos.get("checkout_url") or None,
        "expires_at": _fecha(datos.get("expires_at")),
        "items": items,
        "value": _numero(datos.get("value")),
        "currency": str(datos.get("currency") or "BOB"),
        "messages": mensajes,
    }


async def _pedir(
    metodo: str,
    ruta: str,
    *,
    cart: Cart | None = None,
    json_body: dict | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=12) as cliente:
        respuesta = await cliente.request(
            metodo, f"{_base()}{ruta}", headers=_cabeceras(cart), json=json_body
        )
    if respuesta.status_code == 404:
        raise CarritoVencido("carrito inexistente")
    if respuesta.status_code >= 500:
        raise VtexCartError(f"integrador {respuesta.status_code}")
    if respuesta.status_code >= 400:
        raise VtexCartError(
            f"integrador {respuesta.status_code}: {respuesta.text[:160]}"
        )
    datos = respuesta.json()
    return datos if isinstance(datos, dict) else {}


async def crear_carrito(cart: Cart) -> dict:
    """Crea el carrito y devuelve la respuesta normalizada."""
    if _por_paas():
        datos = await _pedir(
            "POST",
            "/api/vtex/cart",
            cart=cart,
            json_body={
                "sales_channel": settings.vtex_sales_channel,
                "affiliate_id": settings.vtex_affiliate_id or None,
            },
        )
    else:
        datos = await _pedir("POST", "/api/checkout/pub/orderForm", cart=cart)
    carrito = normalizar(datos)
    if not carrito["order_form_id"]:
        raise VtexCartError("sin order_form_id")
    return carrito


async def agregar_items(cart: Cart, items: list[dict]) -> dict:
    """Copia los artículos y devuelve el estado del carrito."""
    cuerpo = {
        "items": [
            {
                "sku": str(item["sku"]),
                "quantity": int(item["quantity"]),
                "seller": str(
                    item.get("seller") or settings.vtex_seller_id or "1"
                ),
            }
            for item in items
            if int(item.get("quantity") or 0) > 0
        ]
    }
    if not cuerpo["items"] or not cart.vtex_order_form_id:
        return normalizar({})
    if _por_paas():
        datos = await _pedir(
            "POST",
            f"/api/vtex/cart/{cart.vtex_order_form_id}/items",
            cart=cart,
            json_body=cuerpo,
        )
    else:
        datos = await _pedir(
            "POST",
            f"/api/checkout/pub/orderForm/{cart.vtex_order_form_id}/items",
            cart=cart,
            json_body=cuerpo,
        )
    return normalizar(datos)


async def consultar(cart: Cart) -> dict | None:
    """Lee el carrito. Devuelve None si ya no existe."""
    if not cart.vtex_order_form_id:
        return None
    ruta = (
        f"/api/vtex/cart/{cart.vtex_order_form_id}"
        if _por_paas()
        else f"/api/checkout/pub/orderForm/{cart.vtex_order_form_id}"
    )
    try:
        datos = await _pedir("GET", ruta, cart=cart)
    except CarritoVencido:
        return None
    return normalizar(datos)


def vencido(cart: Cart) -> bool:
    """¿El carrito ya no sirve?

    Si el integrador informa `expires_at` se respeta; si viene null (hoy)
    se usa el TTL local de 24 h desde la última sincronización.
    """
    informado = getattr(cart, "vtex_expires_at", None)
    if informado is not None:
        if informado.tzinfo is None:
            informado = informado.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > informado
    if not cart.vtex_order_form_id or cart.vtex_synced_at is None:
        return True
    momento = cart.vtex_synced_at
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - momento > timedelta(hours=TTL_HORAS)


def _items_locales(cart: Cart) -> list[dict]:
    return [
        {"sku": item.sku, "quantity": int(item.quantity or 0)}
        for item in cart.items
    ]


def _faltantes(cart: Cart, respuesta: dict) -> list[str]:
    """SKU del carrito local que no quedaron en VTEX."""
    presentes = {
        item["sku"] for item in respuesta["items"] if item["quantity"] > 0
    }
    return [
        item.sku
        for item in cart.items
        if item.sku not in presentes and int(item.quantity or 0) > 0
    ]


async def sincronizar(cart: Cart) -> dict:
    """Deja el carrito de VTEX igual al local.

    Devuelve ``{"estado": ok|incompleto|error, "faltantes": [...],
    "link": str}``. Nunca lanza: el carrito local sigue siendo válido.
    """
    vacio = {
        "estado": "error",
        "faltantes": [],
        "link": "",
        "mensajes": [],
        "detalle": "carrito de VTEX no disponible",
    }
    if not disponible():
        return vacio
    if not cart.items:
        return {
            "estado": "ok",
            "faltantes": [],
            "link": "",
            "mensajes": [],
            "detalle": "",
        }

    try:
        if vencido(cart):
            carrito = await crear_carrito(cart)
            cart.vtex_order_form_id = carrito["order_form_id"]
            cart.vtex_cart_url = carrito["checkout_url"] or ""
        respuesta = await agregar_items(cart, _items_locales(cart))
        faltantes = _faltantes(cart, respuesta)
        # El link viene en la creación; si la respuesta de ítems no lo trae
        # se conserva el que ya teníamos (o se consulta el carrito).
        if not respuesta["checkout_url"] and not cart.vtex_cart_url:
            actual = await consultar(cart)
            if actual is not None:
                respuesta["checkout_url"] = actual["checkout_url"]
        cart.vtex_cart_url = (
            respuesta["checkout_url"] or cart.vtex_cart_url or ""
        )
        cart.vtex_value = respuesta["value"]
        cart.vtex_currency = respuesta["currency"]
        cart.vtex_messages = json.dumps(respuesta["messages"])[:4000]
        if respuesta.get("expires_at") is not None:
            cart.vtex_expires_at = respuesta["expires_at"]
        cart.vtex_synced_at = utcnow()
        if faltantes:
            logger.warning(
                "Carrito %s: el integrador rechazó %s",
                cart.id,
                ", ".join(faltantes),
            )
        return {
            "estado": "incompleto" if faltantes else "ok",
            "faltantes": faltantes,
            "link": cart.vtex_cart_url or "",
            "mensajes": respuesta["messages"],
            "detalle": "",
        }
    except CarritoVencido:
        cart.vtex_order_form_id = ""
        cart.vtex_cart_url = ""
        vacio["detalle"] = "el carrito dio 404"
        return vacio
    except Exception as exc:  # noqa: BLE001 - el carrito local manda
        logger.warning("No se pudo sincronizar el carrito", exc_info=True)
        vacio["detalle"] = str(exc)[:120]
        return vacio


async def asegurar_vigente(cart: Cart) -> bool:
    """Antes de usar el link: confirma que el carrito sigue vigente.

    Si hay id pero no fecha de sincronización, se consulta igual: el carrito
    pudo crearse y fallar la copia de ítems.
    """
    if not cart.vtex_order_form_id:
        return False
    if cart.vtex_synced_at is not None and vencido(cart):
        return False
    actual = await consultar(cart)
    if actual is None:
        return False
    if cart.vtex_synced_at is None:
        cart.vtex_synced_at = utcnow()
    return True


def link_para_pagar(cart: Cart) -> str:
    """Link tal como lo devolvió el integrador (nunca fabricado)."""
    return cart.vtex_cart_url or ""
