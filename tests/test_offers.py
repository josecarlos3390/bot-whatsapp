from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.sap import PricePeriod, QuantityTier, SapItem, build_offer


def _item() -> SapItem:
    return SapItem(
        sku="SKU-1",
        name="Producto",
        price=Decimal("100"),
        stock=10,
        stock_by_store={"101-1001": 6, "102-1001": 0, "103-1001": 4},
    )


def test_offer_uses_base_price_without_period():
    offer = build_offer(_item(), [], quantity=1)
    assert offer.final_price == Decimal("100")
    assert offer.discount_percent == Decimal("0")


def test_offer_applies_active_period_and_quantity_tiers():
    period = PricePeriod(
        valid_from=date.today() - timedelta(days=1),
        valid_to=date.today() + timedelta(days=1),
        price=Decimal("90"),
        tiers=[
            QuantityTier(quantity=3, price=Decimal("80")),
            QuantityTier(quantity=5, price=Decimal("70")),
        ],
    )
    item = _item()

    assert build_offer(item, [period], quantity=1).final_price == Decimal("90")
    assert build_offer(item, [period], quantity=3).final_price == Decimal("80")
    assert build_offer(item, [period], quantity=4).final_price == Decimal("90")
    assert build_offer(item, [period], quantity=5).final_price == Decimal("70")
    assert build_offer(item, [period], quantity=6).final_price == Decimal("90")

    offer = build_offer(item, [period], quantity=3)
    assert [(tier.quantity, tier.price) for tier in offer.tiers] == [
        (3, Decimal("80")),
        (5, Decimal("70")),
    ]
    assert offer.tier_quantity == 3
    assert offer.as_dict()["tiers"][0]["quantity"] == 3


def test_expired_period_is_ignored():
    period = PricePeriod(
        valid_from=date.today() - timedelta(days=10),
        valid_to=date.today() - timedelta(days=2),
        price=Decimal("50"),
    )
    offer = build_offer(_item(), [period], quantity=5)
    assert offer.final_price == Decimal("100")
    assert offer.discount_percent == Decimal("0")


def test_discount_percentage_is_reported():
    period = PricePeriod(
        valid_from=None,
        valid_to=None,
        price=Decimal("80"),
    )
    offer = build_offer(_item(), [period], quantity=1)
    assert offer.final_price == Decimal("80")
    assert offer.discount_percent == Decimal("20.00")
