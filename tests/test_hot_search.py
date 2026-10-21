"""Búsqueda en caliente: lo que no está en el catálogo se trae de SAP y se cachea."""

from __future__ import annotations

from app.models import CatalogItem
from app.services import catalog


class _FakeSap:
    def __init__(self, items: list[dict]):
        self.items = items
        self.calls: list[str] = []

    async def search_items(self, query: str, limit: int = 8) -> list[dict]:
        self.calls.append(query)
        return list(self.items)


async def test_trae_de_sap_y_cachea(session):
    sap = _FakeSap(
        [
            {
                "sku": "SAP-PILLOW-1",
                "name": "COLCHON PILLOW FLEX 2 PLAZAS",
                "price": 3460,
                "stock": 7,
                "currency": "BOB",
            }
        ]
    )

    rows = await catalog.search_with_sap(
        session, "colchon pillow flex 2 plazas", sap=sap, limit=5
    )
    assert [row.sku for row in rows] == ["SAP-PILLOW-1"]
    assert sap.calls, "debe consultar SAP cuando no hay coincidencias locales"

    # Segunda consulta: ya está en la base, no vuelve a SAP.
    calls_before = len(sap.calls)
    rows = await catalog.search_with_sap(
        session, "colchon pillow flex 2 plazas", sap=sap, limit=5
    )
    assert [row.sku for row in rows] == ["SAP-PILLOW-1"]
    assert len(sap.calls) == calls_before


async def test_actualiza_precio_y_stock_si_ya_existe(session):
    session.add(
        CatalogItem(
            sku="SAP-2",
            name="COLCHON VIEJO",
            price=100,
            stock=1,
            active=True,
        )
    )
    await session.commit()

    await catalog.upsert_sap_items(
        session,
        [
            {
                "sku": "SAP-2",
                "name": "COLCHON NUEVO",
                "price": 999,
                "stock": 12,
            }
        ],
    )

    row = await catalog.get_item(session, "SAP-2")
    assert row is not None
    assert row.name == "COLCHON NUEVO"
    assert int(row.price) == 999
    assert row.stock == 12


async def test_no_consulta_sap_si_hay_coincidencia_local(session):
    session.add(
        CatalogItem(
            sku="LOCAL-1",
            name="COLCHON PILLOW FLEX 2 PLAZAS",
            price=100,
            stock=3,
            active=True,
        )
    )
    await session.commit()
    sap = _FakeSap([])

    rows = await catalog.search_with_sap(session, "colchon pillow", sap=sap, limit=5)

    assert [row.sku for row in rows] == ["LOCAL-1"]
    assert sap.calls == []


async def test_ignora_respuestas_incompletas(session):
    sap = _FakeSap([{"sku": "", "name": "SIN SKU"}, {"sku": "OK-1", "name": ""}])
    added = await catalog.upsert_sap_items(session, [*sap.items])
    assert added == 0
