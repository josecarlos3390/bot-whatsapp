"""Las reglas del portal se aplican también en los atajos nuevos."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import AreaRule, CatalogItem, ProductPromotion
from app.services import rule_apply, rule_policy


class _Policy:
    def __init__(self, brand=None, promotion_min=None):
        self.brand = brand
        self.promotion_min = promotion_min

    @property
    def has_product_rules(self):
        return self.brand is not None or self.promotion_min is not None


def _item(sku: str, brand: str, price: float):
    return CatalogItem(
        sku=sku,
        name=f"Producto {sku}",
        price=price,
        stock=5,
        brand=brand,
        category="Heladeras",
        active=True,
    )


def test_la_marca_prioritaria_va_primero():
    productos = [
        _item("A", "ELECTROLUX", 4000),
        _item("B", "SAMSUNG", 7000),
    ]

    ordenados = rule_apply.ordenar(productos, _Policy(brand="Samsung"))

    assert ordenados[0].sku == "B"


def test_sin_reglas_no_cambia_el_orden():
    productos = [_item("A", "LG", 4000), _item("B", "SAMSUNG", 7000)]

    ordenados = rule_apply.ordenar(productos, _Policy())

    assert [x.sku for x in ordenados] == ["A", "B"]


def test_la_promocion_supera_el_minimo_va_primero():
    productos = [_item("A", "LG", 4000), _item("B", "SAMSUNG", 7000)]
    promos = {"B": 30.0, "A": 5.0}

    ordenados = rule_apply.ordenar(
        productos, _Policy(promotion_min=20), promos
    )

    assert ordenados[0].sku == "B"


def test_la_marca_manda_sobre_la_promocion():
    productos = [_item("A", "LG", 4000), _item("B", "SAMSUNG", 7000)]
    promos = {"A": 50.0, "B": 1.0}

    ordenados = rule_apply.ordenar(
        productos, _Policy(brand="Samsung", promotion_min=20), promos
    )

    assert ordenados[0].sku == "B"


async def test_los_descuentos_vigentes_se_leen_de_promociones(session):
    session.add_all(
        [
            ProductPromotion(
                sku="P-1",
                price=100,
                discount_percent=25,
                valid_from=date.today() - timedelta(days=1),
                valid_to=date.today() + timedelta(days=10),
            ),
            ProductPromotion(
                sku="P-2",
                price=100,
                discount_percent=40,
                valid_from=date.today() - timedelta(days=30),
                valid_to=date.today() - timedelta(days=2),
            ),
        ]
    )
    await session.commit()

    promos = await rule_apply.descuentos(session, ["P-1", "P-2"])

    assert promos["P-1"] == 25
    assert "P-2" not in promos  # vencida


async def test_aplicar_usa_las_reglas_de_la_categoria(session):
    samsung = CatalogItem(
        sku="HEL-1",
        name="Heladera Samsung 300L",
        price=8000,
        stock=3,
        brand="SAMSUNG",
        category="Heladeras",
        active=True,
    )
    lg = CatalogItem(
        sku="HEL-2",
        name="Heladera LG 300L",
        price=7000,
        stock=3,
        brand="LG",
        category="Heladeras",
        active=True,
    )
    session.add_all([samsung, lg])
    session.add(
        AreaRule(
            area="ecommerce",
            name="Priorizar Samsung en heladeras",
            rule_type="brand_priority",
            condition={"category": "heladera"},
            action={"brand": "Samsung"},
            priority=90,
            status="published",
        )
    )
    await session.commit()

    ordenados = await rule_apply.aplicar(
        session, "mostrame opciones", [lg, samsung], categoria="heladera"
    )

    assert ordenados[0].brand == "SAMSUNG"


async def test_las_preguntas_obligatorias_se_anexan(session):
    from app.agent import Agent
    from app.models import Contact
    from app.replies import AgentReply
    from app.whatsapp import Outbound

    session.add(
        AreaRule(
            area="ecommerce",
            name="Preguntas antes de vender una heladera",
            rule_type="required_questions",
            condition={"category": "heladera"},
            action={
                "questions": [
                    {"key": "litros", "text": "¿Cuántos litros necesitás?"}
                ]
            },
            priority=50,
            status="published",
        )
    )
    await session.commit()
    contacto = Contact(wa_id="59170060001", phone_e164="+59170060001")
    session.add(contacto)
    await session.commit()

    respuesta = AgentReply([Outbound(text="Estas son las opciones:")])
    final = await rule_apply.anexar_preguntas(
        session, "mostrame las mas elegidas", respuesta, categoria="heladera"
    )

    assert "litros" in (final.messages[-1].text or "")
    assert final.messages[-1].text.rstrip().endswith("?")


async def test_no_repite_la_pregunta_si_ya_esta(session):
    from app.agent import Agent
    from app.replies import AgentReply
    from app.whatsapp import Outbound

    session.add(
        AreaRule(
            area="ecommerce",
            name="Preguntas heladera",
            rule_type="required_questions",
            condition={"category": "heladera"},
            action={
                "questions": [
                    {"key": "litros", "text": "¿Cuántos litros necesitás?"}
                ]
            },
            priority=50,
            status="published",
        )
    )
    await session.commit()

    respuesta = AgentReply(
        [Outbound(text="¿Cuántos litros necesitás?")]
    )
    final = await rule_apply.anexar_preguntas(
        session, "consulta", respuesta, categoria="heladera"
    )

    assert len(final.messages) == 1
