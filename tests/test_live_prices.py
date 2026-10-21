"""La lista de resultados refresca precio y stock contra SAP."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent import Toolbox
from app.config import settings
from app.models import CatalogItem, Contact


class FakeSap:
    """Devuelve precios distintos a los del catálogo (simula SAP actualizado)."""

    def __init__(self):
        self.closed = False

    async def get_offer(self, sku, quantity=1, force_refresh=False):
        return SimpleNamespace(
            sku=sku,
            name=f"Producto {sku}",
            base_price=Decimal("5000.00"),
            final_price=Decimal("4000.00"),
            discount_percent=Decimal("20"),
            stock_by_store={"101-1001": 7},
            is_promotion=True,
        )

    async def close(self):
        self.closed = True


@pytest.fixture
def live_sap(monkeypatch):
    fake = FakeSap()
    monkeypatch.setattr(settings, "sap_mode", "paas")
    monkeypatch.setattr("app.agent.get_sap", lambda session: fake)
    return fake


async def test_la_lista_refresca_precio_y_stock(session, live_sap):
    session.add(
        CatalogItem(
            sku="FRESCO-1",
            name="LAVADORA DE PRUEBA 10KG",
            price=Decimal("6000.00"),
            stock=2,
            active=True,
        )
    )
    contact = Contact(wa_id="59170000961", phone_e164="+59170000961")
    session.add(contact)
    await session.commit()

    result = await Toolbox(session, contact, None).tool_search_products(
        query="lavadora de prueba", limit=3
    )

    product = result["products"][0]
    assert product["price"] == "5000.00"
    assert product["promo_price"] == "4000.00"
    assert product["stock"] == 7
    assert live_sap.closed is True


async def test_si_sap_falla_queda_el_precio_del_catalogo(session, monkeypatch):
    class BrokenSap(FakeSap):
        async def get_offer(self, sku, quantity=1, force_refresh=False):
            raise RuntimeError("SAP caído")

    monkeypatch.setattr(settings, "sap_mode", "paas")
    monkeypatch.setattr("app.agent.get_sap", lambda session: BrokenSap())

    session.add(
        CatalogItem(
            sku="FRESCO-2",
            name="TALADRO DE PRUEBA 500W",
            price=Decimal("350.00"),
            stock=4,
            active=True,
        )
    )
    contact = Contact(wa_id="59170000962", phone_e164="+59170000962")
    session.add(contact)
    await session.commit()

    result = await Toolbox(session, contact, None).tool_search_products(
        query="taladro de prueba", limit=3
    )

    assert result["products"][0]["price"] == "350.00"
