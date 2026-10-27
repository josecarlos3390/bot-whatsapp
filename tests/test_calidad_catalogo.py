"""Informe de calidad del catálogo."""

from __future__ import annotations

from app.models import CatalogItem, ProductImage
from app.services import catalog_quality


async def test_detecta_defectos_del_catalogo(session):
    session.add_all(
        [
            CatalogItem(
                sku="OK-1",
                name="Taladro Percutor 13mm Ingco TALADRO PERCUTOR 13MM INGCO",
                price=500,
                stock=5,
                category="Taladros",
                brand="INGCO",
                active=True,
            ),
            CatalogItem(
                sku="SIN-FOTO",
                name="Martillo Galponero 29mm Tramontina MARTILLO GALPONERO 29MM",
                price=80,
                stock=3,
                category="Herramientas manuales",
                brand="TRAMONTINA",
                active=True,
            ),
            CatalogItem(
                sku="CRUZADO",
                name=(
                    "Taladro Percutor 20v Ingco BROCA PARA SIERRA COPA 7/16PLG "
                    "32-210MM INGCO"
                ),
                price=900,
                stock=2,
                category="Taladros",
                brand="INGCO",
                active=True,
            ),
            CatalogItem(
                sku="CAT-SOLA",
                name="Nivel Laser 360 Auto Ingco NIVEL LASER 360 INGCO",
                price=700,
                stock=1,
                category="Niveles",
                brand="INGCO",
                active=True,
            ),
        ]
    )
    session.add(
        ProductImage(
            sku="OK-1",
            url="https://example.com/ok.png",
            position=0,
            is_primary=True,
            approved=True,
        )
    )
    await session.commit()

    informe = await catalog_quality.report(session)

    assert informe["total"] >= 4
    assert informe["sin_foto"] >= 1
    assert informe["sin_foto"] >= 1
    assert informe["nombres_cruzados"] >= 1
    assert any(
        fila["category"] == "Niveles" for fila in informe["categorias_chicas"]
    )


async def test_informe_sin_defectos(session):
    session.add(
        CatalogItem(
            sku="LIMPIO",
            name="Destornillador Plano 6mm Stanley DESTORNILLADOR PLANO 6MM",
            price=40,
            stock=10,
            category="Herramientas manuales",
            brand="STANLEY",
            active=True,
        )
    )
    session.add(
        ProductImage(
            sku="LIMPIO",
            url="https://example.com/limpio.png",
            position=0,
            is_primary=True,
            approved=True,
        )
    )
    await session.commit()

    informe = await catalog_quality.report(session)

    assert informe["sin_precio"] == 0
    assert isinstance(informe["busquedas_pendientes"], list)
