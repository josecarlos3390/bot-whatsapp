from __future__ import annotations

from datetime import date, timedelta

from app.models import (
    Contact,
    ProductPromotion,
    PurchaseHistory,
    PurchaseHistoryLine,
)
from app.services import purchases
from app.services import customer_analysis


async def _customer_with_history(session):
    contact = Contact(
        wa_id="59170000777",
        phone_e164="+59170000777",
        name="Cliente historial",
    )
    session.add(contact)
    await session.commit()
    history = PurchaseHistory(
        contact_id=contact.id,
        sap_doc_entry=9001,
        doc_type="invoice",
        doc_num=9001,
        doc_date=date.today() - timedelta(days=10),
        total=100,
    )
    session.add(history)
    await session.flush()
    session.add(
        PurchaseHistoryLine(
            history_id=history.id,
            sku="FILT-001",
            name="Filtro de prueba",
            category="Filtros",
            quantity=1,
            amount=85,
        )
    )
    session.add(
        ProductPromotion(
            sku="FILT-001",
            price=50,
            discount_percent=41.18,
            valid_from=date.today() - timedelta(days=1),
            valid_to=date.today() + timedelta(days=10),
            tier_quantity=None,
            price_list=1,
        )
    )
    await session.commit()
    return contact


async def test_history_summary_and_recommendation(session):
    contact = await _customer_with_history(session)
    summary = await purchases.history_summary(session, contact.id)
    assert summary["count"] == 1
    assert summary["top_categories"][0]["category"] == "Filtros"

    analysis = await customer_analysis.analyze_customer(session, contact.id)
    assert analysis["frequency"] == 1
    assert analysis["segment"] == "nuevo"
    assert analysis["avg_ticket"] == "100.00"

    history = await purchases.get_history(session, contact.id)
    assert history["purchases"][0]["lines"][0]["sku"] == "FILT-001"

    result = await purchases.recommend_for_customer(
        session, contact.id, limit=3
    )
    assert result["cold_start"] is False
    assert result["recommendations"]
    assert result["recommendations"][0]["reason"].startswith("Ya compraste")


async def test_memory_includes_purchase_summary(session):
    from app.services import memory

    contact = await _customer_with_history(session)
    text = await memory.memory_text(session, contact, "conv-x")
    assert "Compras: 1" in text
