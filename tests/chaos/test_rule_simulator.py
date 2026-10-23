"""El simulador debe mostrar productos y reglas sin crear conversaciones."""

from __future__ import annotations

from app.models import AreaRule, CatalogItem
from app.services import rule_simulator


async def test_simulador_aplica_regla_de_marca(session):
    session.add(
        AreaRule(
            area="ecommerce",
            name="Priorizar LG en televisores",
            rule_type="brand_priority",
            condition={"category": "televisor"},
            action={"brand": "LG"},
            priority=100,
            status="published",
        )
    )
    session.add(
        CatalogItem(
            sku="SIM-TV-LG",
            name="TELEVISOR SIMULADOR LG 50",
            category="TV",
            brand="LG",
            price=3000,
            stock=2,
            active=True,
        )
    )
    await session.commit()

    result = await rule_simulator.simulate(
        session, query="televisor", area="ecommerce"
    )
    assert result["ok"] is True
    assert any(rule["name"] == "Priorizar LG en televisores" for rule in result["rules"])
    assert any(product["sku"] == "SIM-TV-LG" for product in result["products"])
