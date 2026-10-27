"""Preparación para producción y feed del catálogo."""

from __future__ import annotations

from app.models import Advisor, CatalogItem, ProductImage
from app.services import native_commerce, readiness


async def test_readiness_lista_los_criterios(session):
    session.add(
        CatalogItem(
            sku="READY-1",
            name="Destornillador Plano 6mm Stanley",
            price=40,
            stock=10,
            category="Herramientas manuales",
            brand="STANLEY",
            active=True,
        )
    )
    session.add(
        ProductImage(
            sku="READY-1",
            url="https://example.com/d.png",
            position=0,
            is_primary=True,
            approved=True,
        )
    )
    session.add(Advisor(username="guardia1", display_name="Guardia", password_hash="x", active=True, on_duty=True))
    await session.commit()

    datos = await readiness.readiness(session)

    assert "score" in datos
    assert datos["score"].endswith("/8")
    claves = {c["key"] for c in datos["criteria"]}
    assert {"fotos", "titulos", "politicas", "feed", "nativo", "guardia"} <= claves
    assert any(c["key"] == "presupuesto" and c.get("manual") for c in datos["criteria"])


async def test_feed_omite_productos_sin_foto(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "meta_catalog_placeholder_image", "")
    session.add_all(
        [
            CatalogItem(
                sku="FEED-OK",
                name="Martillo Galponero 29mm",
                price=80,
                stock=3,
                category="Herramientas",
                active=True,
            ),
            CatalogItem(
                sku="FEED-NO",
                name="Producto sin imagen",
                price=50,
                stock=2,
                category="Herramientas",
                active=True,
            ),
        ]
    )
    session.add(
        ProductImage(
            sku="FEED-OK",
            url="https://example.com/m.png",
            position=0,
            is_primary=True,
            approved=True,
        )
    )
    await session.commit()

    filas, omitidos = await native_commerce.catalog_feed(session, limit=50)

    ids = {fila["id"] for fila in filas}
    assert "FEED-OK" in ids
    assert "FEED-NO" not in ids
    assert omitidos >= 0
