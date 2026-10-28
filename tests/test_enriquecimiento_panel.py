"""Progreso del enriquecimiento VTEX en el panel."""

from __future__ import annotations

from app.services import catalog_quality


async def test_el_informe_cuenta_enriquecidos(session):
    from app.models import CatalogItem

    session.add_all(
        [
            CatalogItem(
                sku="ENR-1",
                name="Silla Cuerina Plomo",
                price=450,
                stock=3,
                category="Sillas",
                attributes={"keywords_source": "vtex", "color": "Plomo"},
                active=True,
            ),
            CatalogItem(
                sku="ENR-2",
                name="Silla Sin enriquecer",
                price=300,
                stock=1,
                category="Sillas",
                attributes={},
                active=True,
            ),
        ]
    )
    await session.commit()

    informe = await catalog_quality.report(session)

    assert informe["enriquecidos"] >= 1
    assert informe["total"] >= 2
    assert 0 <= informe["enriquecidos_pct"] <= 100
