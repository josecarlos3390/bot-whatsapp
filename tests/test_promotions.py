from __future__ import annotations

from datetime import date, timedelta

from app.agent import Toolbox
from app.models import Contact, ProductPromotion


async def test_list_promotions_returns_active_discount(session):
    contact = Contact(wa_id="59170000999", phone_e164="+59170000999", name="Test")
    session.add(contact)
    session.add(
        ProductPromotion(
            sku="FILT-001",
            price=50,
            discount_percent=41.18,
            valid_from=date.today() - timedelta(days=1),
            valid_to=date.today() + timedelta(days=1),
            tier_quantity=None,
            price_list=1,
        )
    )
    await session.commit()

    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_list_promotions(limit=5)
    assert result["ok"] is True
    assert result["promotions"]
    promo = result["promotions"][0]
    assert promo["sku"] == "FILT-001"
    assert float(promo["discount_percent"]) > 40
    assert promo["stock"] > 0


async def test_list_promotions_empty(session):
    contact = Contact(wa_id="59170000998", phone_e164="+59170000998")
    session.add(contact)
    await session.commit()

    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_list_promotions(limit=5)
    assert result["ok"] is True
    assert result["promotions"] == []
    assert result["note"]
