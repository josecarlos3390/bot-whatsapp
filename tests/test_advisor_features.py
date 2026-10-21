"""Escalones por cantidad y complementos con stock."""

from __future__ import annotations

from decimal import Decimal

from app.models import CatalogItem, ProductPromotion
from app.services import catalog


async def test_quantity_tiers_vigentes(session):
    session.add_all(
        [
            ProductPromotion(
                sku="FILT-001",
                price=Decimal("70"),
                tier_quantity=3,
                price_list=1,
            ),
            ProductPromotion(
                sku="FILT-001",
                price=Decimal("60"),
                tier_quantity=6,
                price_list=1,
            ),
        ]
    )
    await session.commit()

    tiers = await catalog.quantity_tiers(session, "filt-001")

    assert tiers == [(3, Decimal("70")), (6, Decimal("60"))]


async def test_complementos_solo_con_stock(session):
    session.add_all(
        [
            CatalogItem(
                sku="COLCH-1",
                name="COLCHON PILLOW 2 PLAZAS",
                price=3000,
                stock=4,
                active=True,
            ),
            CatalogItem(
                sku="ALM-0",
                name="ALMOHADA SIN STOCK",
                price=100,
                stock=0,
                active=True,
            ),
            CatalogItem(
                sku="ALM-1",
                name="ALMOHADA PLUS 50X70",
                price=149,
                stock=6,
                active=True,
            ),
        ]
    )
    await session.commit()

    combo = await catalog.complements(
        session, "COLCH-1", "COLCHON PILLOW 2 PLAZAS", limit=1
    )

    assert [row.sku for row in combo] == ["ALM-1"]


async def test_sin_complemento_para_categorias_desconocidas(session):
    combo = await catalog.complements(session, "X-1", "ADORNO DE PARED", limit=1)
    assert combo == []
