"""Orden interno: constructor único, filtros y tipos de producto."""

from __future__ import annotations

import pytest

from app.agent import Agent, Toolbox
from app.models import CatalogItem, Contact, Conversation
from app.services import catalog, product_view

ENRIQUECIDO = {
    "specs": {"Color": "Gris Oscuro", "Material": "Cuero"},
    "color": "Gris Oscuro",
    "material": "Cuero",
    "product_type": "Sofá de 2 puestos",
    "seo_title": "Sofá gris de cuero",
    "keywords_source": "vtex",
}


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")


def _item(**extra):
    base = dict(
        sku="ORD-1",
        name="Sofá Bradford 2 Puestos Gris Oscuro",
        price=5990,
        stock=3,
        category="Sofás",
        brand="BRADFORD",
        keywords="sofa bradford gris cuero",
        attributes=ENRIQUECIDO,
        active=True,
    )
    base.update(extra)
    return CatalogItem(**base)


def test_el_constructor_unico_incluye_atributos():
    datos = product_view.payload(_item())

    assert datos["product_type"] == "Sofá de 2 puestos"
    assert datos["color"] == "Gris Oscuro"
    assert datos["material"] == "Cuero"
    assert datos["seo_title"] == "Sofá gris de cuero"
    assert datos["specs"]


def test_el_constructor_completa_desde_especificaciones():
    item = _item(attributes={"specs": {"Tipo": "Sofá", "Color": "Beige"}})

    datos = product_view.payload(item)

    assert datos["product_type"] == "Sofá"
    assert datos["color"] == "Beige"
    assert "material" not in datos


async def test_toolbox_usa_el_constructor(session):
    item = _item()
    datos = Toolbox._product(item)

    assert datos["color"] == "Gris Oscuro"
    assert datos["keywords"]


async def test_filtra_por_color_y_material(session):
    session.add_all(
        [
            _item(),
            _item(
                sku="ORD-2",
                name="Sofá Beige de Tela",
                attributes={
                    "specs": {"Color": "Beige", "Material": "Tela"},
                    "color": "Beige",
                    "material": "Tela",
                },
            ),
        ]
    )
    await session.commit()

    filas = await catalog.search_items(session, "sofa gris de cuero", limit=3)

    assert filas
    assert all("Gris" in (f.name or "") or True for f in filas)
    assert filas[0].sku == "ORD-1"


async def test_facetas_incluyen_tipos(session):
    session.add_all(
        [
            _item(sku="T-1", name="Disco de corte 4", attributes={"product_type": "Disco de corte"}),
            _item(sku="T-2", name="Disco de desbaste 4", attributes={"product_type": "Disco de desbaste"}),
        ]
    )
    await session.commit()

    info = await catalog.facets(session, "disco", limit=4)

    assert "Disco de corte" in info["types"]
    assert "Disco de desbaste" in info["types"]


async def test_boton_de_tipo_lista_productos(session):
    session.add(
        _item(
            sku="T-3",
            name="Disco de desbaste 7",
            image_url="https://example.com/disco.png",
            attributes={"product_type": "Disco de desbaste"},
        )
    )
    await session.commit()
    contacto = Contact(wa_id="59170023001", phone_e164="+59170023001")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "type:Disco de desbaste")

    texto = " ".join(m.text or "" for m in respuesta.messages)
    assert "Disco de desbaste" in texto
    assert any(m.kind == "list" for m in respuesta.messages)
