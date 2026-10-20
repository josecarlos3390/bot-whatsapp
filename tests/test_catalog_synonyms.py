from __future__ import annotations

from app.models import CatalogItem
from app.services import catalog


def test_variants_include_synonyms():
    variants = catalog._variants("refri")
    assert "refri" in variants
    assert "refrigerador" in variants


def test_variants_fold_accents():
    variants = catalog._variants("colchón")
    assert "colchon" in variants


async def test_search_synonym_and_intent(session):
    session.add_all(
        [
            CatalogItem(
                sku="SYN-1",
                name="REFRIGERADOR 300L INOX",
                category="LINEA BLANCA",
                price=1000,
                stock=2,
            ),
            CatalogItem(
                sku="SYN-2",
                name="SILLON LIVING 2 CUERPOS",
                category="MUEBLES",
                price=800,
                stock=3,
            ),
            CatalogItem(
                sku="SYN-3",
                name="COLCHON QUEEN 160X200",
                category="DECO HOGAR",
                price=500,
                stock=4,
            ),
        ]
    )
    await session.commit()

    refri = await catalog.search_items(session, "refri", limit=3)
    assert refri and refri[0].sku == "SYN-1"

    living = await catalog.search_items(session, "living", limit=3)
    assert living and living[0].sku == "SYN-2"

    colchon = await catalog.search_items(session, "colchón", limit=3)
    assert colchon and colchon[0].sku == "SYN-3"

    typo = await catalog.search_items(session, "refirgerador", limit=3)
    assert typo and typo[0].sku == "SYN-1"
