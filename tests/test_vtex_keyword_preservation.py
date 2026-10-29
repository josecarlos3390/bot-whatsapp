"""El sync de catálogo no debe borrar keywords ya enriquecidas."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import CatalogItem
from scripts.sync_vtex import _upsert_item


async def test_sync_preserva_keywords_y_columnas_vtex(session):
    item = CatalogItem(
        sku="KEEP-1",
        name="Producto existente",
        category="TV",
        brand="LG",
        price=100,
        stock=2,
        keywords="keyword real de vtex",
        keywords_source="vtex",
        keywords_synced_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
        product_type="Televisor",
        color="Negro",
        material="Plástico",
        attributes={
            "specs": {"Tipo": "Televisor", "Color": "Negro"},
            "keywords_source": "vtex",
        },
    )
    session.add(item)
    await session.commit()

    await _upsert_item(
        session,
        {
            "sku": "KEEP-1",
            "name": "Producto existente actualizado",
            "category": "TV",
            "brand": "LG",
            "price": 120,
            "stock": 3,
            "description": "Nueva descripción",
        },
    )
    await session.commit()
    await session.refresh(item)

    assert item.keywords == "keyword real de vtex"
    assert item.keywords_source == "vtex"
    assert item.keywords_synced_at is not None
    assert item.product_type == "Televisor"
    assert item.color == "Negro"
    assert item.material == "Plástico"
    assert item.attributes["keywords_source"] == "vtex"
    assert item.attributes["specs"]["Tipo"] == "Televisor"
    assert item.price == 120
