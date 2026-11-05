"""Detección del pedido creado en VTEX a partir del carrito."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent import Agent
from app.config import settings
from app.models import Cart, CartItem, CatalogItem, Contact, Conversation
from app.services import cart as cart_service
from app.services import vtex_pedidos


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.local")
    monkeypatch.setattr(settings, "sap_paas_api_key", "llave")
    monkeypatch.setattr(settings, "sap_paas_tenant", "RETAIL_QA5")
    vtex_pedidos.olvidar()


def test_traduce_los_estados():
    assert vtex_pedidos.estado_legible("ready-for-handling") == "en preparación"
    assert vtex_pedidos.estado_legible("payment-approved") == "pago aprobado"
    assert vtex_pedidos.estado_legible("canceled") == "cancelado"


def test_un_estado_desconocido_se_lee_igual():
    assert vtex_pedidos.estado_legible("nuevo-estado") == "nuevo estado"


async def test_encuentra_el_pedido_del_carrito(monkeypatch):
    async def _pedidos():
        return [
            {"orderId": "1-01", "orderFormId": "OTRO", "status": "canceled"},
            {
                "orderId": "1672-01",
                "orderFormId": "OF-1",
                "sequence": "500195",
                "status": "payment-approved",
                "totalValue": 220.0,
            },
        ]

    monkeypatch.setattr(vtex_pedidos, "_pedidos", _pedidos)

    encontrado = await vtex_pedidos.del_carrito("of-1")

    assert encontrado is not None
    assert encontrado["order_id"] == "1672-01"
    assert encontrado["status_legible"] == "pago aprobado"


async def test_sin_pedido_devuelve_none(monkeypatch):
    async def _pedidos():
        return [{"orderId": "1-01", "orderFormId": "OTRO", "status": "handling"}]

    monkeypatch.setattr(vtex_pedidos, "_pedidos", _pedidos)

    assert await vtex_pedidos.del_carrito("OF-1") is None


async def test_el_bot_avisa_que_el_pedido_ya_existe(session, monkeypatch):
    session.add(
        CatalogItem(
            sku="PED-1",
            name="Producto Pedido",
            price="100",
            stock=5,
            brand="TEST",
            category="Pintura",
            active=True,
        )
    )
    await session.commit()

    contacto = Contact(
        wa_id="59170070001", phone_e164="+59170070001", name="Ana"
    )
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    await Agent().handle(session, contacto, "add:PED-1:2")
    carrito = await cart_service.get_or_create_cart(session, contacto.id)
    carrito.vtex_order_form_id = "OF-1"
    await session.commit()

    async def _pedidos():
        return [
            {
                "orderId": "1672-01",
                "orderFormId": "OF-1",
                "sequence": "500195",
                "status": "payment-approved",
            }
        ]

    monkeypatch.setattr(vtex_pedidos, "_pedidos", _pedidos)

    respuesta = await Agent().handle(session, contacto, "carrito")
    texto = respuesta.messages[0].text or ""

    assert "500195" in texto
    assert "pago aprobado" in texto.lower()

    await session.refresh(carrito)
    assert carrito.status == "ordered"
    assert carrito.vtex_order_id == "1672-01"
