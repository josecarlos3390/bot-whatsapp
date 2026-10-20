from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.models import ProductPromotion
from app.services import pricing


class FailingSap:
    async def get_offer(self, sku, quantity=1, force_refresh=False):
        raise RuntimeError("SAP down")


def _promo(tier, price, discount):
    return ProductPromotion(
        sku="FILT-001",
        price=price,
        discount_percent=discount,
        valid_from=date.today() - timedelta(days=1),
        valid_to=date.today() + timedelta(days=10),
        tier_quantity=tier,
        price_list=1,
    )


async def test_local_offer_applies_period_and_exact_tier(session):
    session.add(_promo(None, 50, 41.18))
    session.add(_promo(3, 40, 52.94))
    await session.commit()

    one = await pricing.local_offer(session, "FILT-001", 1)
    three = await pricing.local_offer(session, "FILT-001", 3)
    assert one is not None and one.final_price == Decimal("50")
    assert three is not None and three.final_price == Decimal("40")
    assert three.tier_quantity == 3


async def test_fallback_only_when_not_checkout(session):
    offer = await pricing.get_offer(
        session, "FILT-001", 1, sap=FailingSap()
    )
    assert offer is not None
    assert offer.final_price == Decimal("85")

    try:
        await pricing.get_offer(
            session,
            "FILT-001",
            1,
            force_refresh=True,
            sap=FailingSap(),
        )
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Checkout debe fallar si SAP no responde")
