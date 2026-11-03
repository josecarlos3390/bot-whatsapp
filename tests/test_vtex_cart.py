"""Carrito espejo en VTEX (orderForm)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import settings
from app.models import Cart, CartItem, CatalogItem, Contact
from app.services import vtex_cart


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "vtex_cart_enabled", True)
    monkeypatch.setattr(settings, "vtex_account", "roho")
    monkeypatch.setattr(settings, "vtex_environment", "vtexcommercestable")
    monkeypatch.setattr(settings, "vtex_app_key", "clave")
    monkeypatch.setattr(settings, "vtex_app_token", "token")
    monkeypatch.setattr(settings, "vtex_sales_channel", 1)
    monkeypatch.setattr(settings, "vtex_affiliate_id", "")
    monkeypatch.setattr(settings, "vtex_checkout_host", "")


async def _carrito(session) -> Cart:
    contacto = Contact(
        wa_id="59170050001", phone_e164="+59170050001", name="Ana"
    )
    session.add(contacto)
    await session.flush()
    carrito = Cart(contact_id=contacto.id, status="active")
    session.add(carrito)
    await session.flush()
    session.add(
        CartItem(
            cart_id=carrito.id,
            sku="VTX-001",
            quantity=2,
            unit_price=Decimal("100"),
            list_price=Decimal("100"),
        )
    )
    await session.commit()
    await session.refresh(carrito, attribute_names=["items"])
    return carrito


def test_sin_credenciales_no_esta_disponible(monkeypatch):
    monkeypatch.setattr(settings, "vtex_app_key", "")

    assert not vtex_cart.disponible()


def test_el_link_apunta_al_carrito():
    enlace = vtex_cart.url_para_cliente("ABC123")

    assert enlace.endswith("/checkout/#/orderform/ABC123")
    assert enlace.startswith("https://roho.vtexcommercestable.com.br")


def test_el_link_usa_el_dominio_del_cliente(monkeypatch):
    monkeypatch.setattr(settings, "vtex_checkout_host", "https://roho.com.bo")

    assert vtex_cart.url_para_cliente("ABC").startswith(
        "https://roho.com.bo/checkout/"
    )


async def test_sincronizar_crea_el_carrito_y_guarda_el_link(
    session, monkeypatch
):
    carrito = await _carrito(session)
    llamadas: list[tuple[str, str]] = []

    async def _fake_pedir(metodo, ruta, json=None):
        llamadas.append((metodo, ruta))
        if ruta.startswith("/api/checkout/pub/orderForm?"):
            return {"orderFormId": "OF-1"}
        return {"items": json.get("items") if json else []}

    monkeypatch.setattr(vtex_cart, "_pedir", _fake_pedir)

    await vtex_cart.sincronizar(carrito)

    assert carrito.vtex_order_form_id == "OF-1"
    assert carrito.vtex_cart_url.endswith("/orderform/OF-1")
    assert [ruta for _m, ruta in llamadas][0].startswith("/api/checkout/pub/orderForm")


async def test_si_vtex_falla_el_carrito_local_sigue(session, monkeypatch):
    carrito = await _carrito(session)

    async def _falla(*args, **kwargs):
        raise vtex_cart.VtexCartError("sin conexión")

    monkeypatch.setattr(vtex_cart, "_pedir", _falla)

    await vtex_cart.sincronizar(carrito)

    assert carrito.vtex_order_form_id is None
    assert vtex_cart.link_para_pagar(carrito) == ""


async def test_sin_items_no_llama_a_vtex(session, monkeypatch):
    carrito = await _carrito(session)
    for item in list(carrito.items):
        await session.delete(item)
    await session.commit()
    await session.refresh(carrito, attribute_names=["items"])

    llamado = {"veces": 0}

    async def _fake(*args, **kwargs):
        llamado["veces"] += 1
        return {}

    monkeypatch.setattr(vtex_cart, "_pedir", _fake)
    await vtex_cart.sincronizar(carrito)

    assert llamado["veces"] == 0
