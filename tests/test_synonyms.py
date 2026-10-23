"""Sinónimos: el cliente no usa las mismas palabras que el catálogo VTEX."""

from __future__ import annotations

from app.services import catalog


async def test_lavarropas_encuentra_lavadoras(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="LAV-1",
            name="LAVADORA 10KG CARGA FRONTAL",
            price=5000,
            stock=3,
            active=True,
        )
    )
    await session.commit()

    rows = await catalog.search_items(session, "lavarropas", limit=5)

    assert [row.sku for row in rows] == ["LAV-1"]


async def test_colchoneta_encuentra_colchones(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="COL-1",
            name="COLCHON 2 PLAZAS 140X190",
            price=2000,
            stock=2,
            active=True,
        )
    )
    await session.commit()

    rows = await catalog.search_items(session, "colchoneta 2 plazas", limit=5)

    assert [row.sku for row in rows] == ["COL-1"]


async def test_refrigerador_encuentra_refri(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="REF-1",
            name="REFRIGERADORA NO FROST 300L",
            price=4000,
            stock=1,
            active=True,
        )
    )
    await session.commit()

    rows = await catalog.search_items(session, "refrigerador", limit=5)

    # "refri" también matchea REFRIGERANTE, pero el refrigerador va primero.
    assert rows[0].sku == "REF-1"


async def test_pulgada_encuentra_plg(session):
    from app.models import CatalogItem

    session.add(
        CatalogItem(
            sku="BRO-1",
            name="BROCHA 2 PLG CERDA PET",
            price=15,
            stock=10,
            active=True,
        )
    )
    await session.commit()

    rows = await catalog.search_items(session, "brocha 2 pulgadas", limit=5)

    assert [row.sku for row in rows] == ["BRO-1"]
