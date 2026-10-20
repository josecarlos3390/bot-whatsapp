from __future__ import annotations

import asyncio
from decimal import Decimal

from app.sap import HybridSap, SapItem


class FakeReader:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def get_item(self, sku: str, force_refresh: bool = False):
        self.calls += 1
        if self.fail:
            raise RuntimeError("SAP caído")
        return SapItem(sku=sku, name="Producto", price=Decimal("100"), stock=5)

    async def create_sales_order(self, order):
        raise NotImplementedError

    async def create_invoice_from_order(self, order):
        raise NotImplementedError

    async def create_incoming_payment(self, order, invoice):
        raise NotImplementedError


class FakeWriter(FakeReader):
    pass


async def test_cache_hits_and_force_refresh():
    reader = FakeReader()
    sap = HybridSap(reader=reader, writer=FakeWriter(), ttl_seconds=60)

    first = await sap.get_item("SKU-1")
    second = await sap.get_item("SKU-1")
    assert first == second
    assert reader.calls == 1

    await sap.get_item("SKU-1", force_refresh=True)
    assert reader.calls == 2


async def test_stale_cache_is_used_if_sap_fails():
    reader = FakeReader()
    sap = HybridSap(reader=reader, writer=FakeWriter(), ttl_seconds=0)
    await sap.get_item("SKU-2")
    reader.fail = True
    item = await sap.get_item("SKU-2")
    assert item is not None and item.price == Decimal("100")


async def test_force_refresh_raises_if_sap_fails():
    reader = FakeReader()
    reader.fail = True
    sap = HybridSap(reader=reader, writer=FakeWriter(), ttl_seconds=60)
    try:
        await sap.get_item("SKU-3", force_refresh=True)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Se esperaba el error de SAP")


async def test_concurrent_requests_share_one_live_call():
    reader = FakeReader()
    sap = HybridSap(reader=reader, writer=FakeWriter(), ttl_seconds=60)
    results = await asyncio.gather(
        *[sap.get_item("SKU-4") for _ in range(10)]
    )
    assert all(item and item.sku == "SKU-4" for item in results)
    assert reader.calls == 1
