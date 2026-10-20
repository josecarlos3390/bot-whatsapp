from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.agent import Toolbox
from app.models import CatalogItem, Contact, ProductSalesStat
from app.services import sales_stats


def test_aggregate_invoice_docs():
    today = date.today()
    stats = sales_stats.aggregate_invoice_docs(
        [
            {
                "DocDate": (today - timedelta(days=5)).isoformat(),
                "DocumentLines": [
                    {"ItemCode": "A", "Quantity": 2, "LineTotal": 200},
                    {"ItemCode": "B", "Quantity": 1, "LineTotal": 50},
                ],
            },
            {
                "DocDate": (today - timedelta(days=60)).isoformat(),
                "DocumentLines": [
                    {"ItemCode": "A", "Quantity": 3, "LineTotal": 300}
                ],
            },
        ],
        today=today,
    )
    assert stats["A"]["units_30d"] == 2
    assert stats["A"]["units_90d"] == 5
    assert stats["A"]["revenue_30d"] == Decimal("200")
    assert stats["A"]["revenue_90d"] == Decimal("500")
    assert stats["B"]["units_30d"] == 1


async def test_best_sellers_and_tool(session):
    contact = Contact(wa_id="59170000333", phone_e164="+59170000333")
    session.add(contact)
    session.add(
        ProductSalesStat(
            sku="FILT-001",
            units_30d=10,
            revenue_30d=500,
            units_90d=25,
            revenue_90d=1200,
            last_sale_date=date.today(),
        )
    )
    await session.commit()

    rows = await sales_stats.best_sellers(session, limit=3)
    assert rows and rows[0]["sku"] == "FILT-001"

    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_get_best_sellers(limit=3)
    assert result["ok"] is True
    assert result["products"][0]["units_30d"] == 10
    assert "Filtro" in result["products"][0]["name"]
