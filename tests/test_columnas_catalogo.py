"""Columnas de clasificación: tipo, color y material."""

from __future__ import annotations

from app.models import CatalogItem
from app.services import catalog, product_view


def _item(**extra):
    base = dict(
        sku="COL-1",
        name="Silla Cuerina Plomo",
        price=450,
        stock=3,
        category="Sillas",
        active=True,
    )
    base.update(extra)
    return CatalogItem(**base)


def test_las_columnas_son_la_fuente_principal():
    item = _item(
        product_type="Silla para comedor",
        color="Plomo",
        material="Cuerina",
        keywords_source="vtex",
        attributes={"product_type": "Otro tipo", "color": "Otro"},
    )

    datos = product_view.payload(item)

    assert datos["product_type"] == "Silla para comedor"
    assert datos["color"] == "Plomo"
    assert datos["material"] == "Cuerina"


def test_si_falta_la_columna_usa_el_json():
    item = _item(
        attributes={
            "product_type": "Silla",
            "specs": {"Color": "Beige", "Material": "Tela"},
        }
    )

    datos = product_view.payload(item)

    assert datos["product_type"] == "Silla"
    assert datos["color"] == "Beige"
    assert datos["material"] == "Tela"


async def test_la_busqueda_por_tipo_usa_la_columna(session):
    session.add(
        _item(
            sku="COL-2",
            name="Disco de desbaste 7",
            product_type="Disco de desbaste",
        )
    )
    session.add(
        _item(
            sku="COL-3",
            name="Disco de corte 7",
            product_type="Disco de corte",
        )
    )
    await session.commit()

    filas = await catalog.search_by_type(session, "Disco de desbaste", limit=5)

    assert [fila.sku for fila in filas] == ["COL-2"]


async def test_las_facetas_cuentan_la_columna(session):
    session.add_all(
        [
            _item(sku="COL-4", name="Disco de corte 4", product_type="Disco de corte"),
            _item(sku="COL-5", name="Disco de desbaste 4", product_type="Disco de desbaste"),
        ]
    )
    await session.commit()

    info = await catalog.facets(session, "disco", limit=4)

    assert "Disco de corte" in info["types"]
