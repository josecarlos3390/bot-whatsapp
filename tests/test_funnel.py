"""Embudo de venta: registro y conversión entre pasos."""

from __future__ import annotations

from decimal import Decimal

from app.models import Contact
from app.services import funnel


async def test_registra_y_cuenta_pasos(session):
    contact = Contact(wa_id="59170000981", phone_e164="+59170000981")
    session.add(contact)
    await session.commit()

    await funnel.track(
        session, "search", contact=contact, query="colchon 2 plazas"
    )
    await funnel.track(session, "product_view", contact=contact, sku="COL-1")
    await funnel.track(
        session, "cart_add", contact=contact, sku="COL-1", value=Decimal("2190")
    )
    await session.commit()

    data = await funnel.stats(session, 30)
    steps = {row["step"]: row for row in data["steps"]}

    assert steps["search"]["contacts"] == 1
    assert steps["cart_add"]["contacts"] == 1
    assert steps["checkout_start"]["contacts"] == 0
    assert steps["product_view"]["conversion"] == 100.0
    assert steps["checkout_start"]["conversion"] == 0.0


async def test_ignora_paso_desconocido(session):
    contact = Contact(wa_id="59170000982", phone_e164="+59170000982")
    session.add(contact)
    await session.commit()

    await funnel.track(session, "paso_inventado", contact=contact)
    await session.commit()

    data = await funnel.stats(session, 30)
    assert all(row["events"] == 0 for row in data["steps"])


async def test_cuenta_contactos_unicos(session):
    first = Contact(wa_id="59170000983", phone_e164="+59170000983")
    second = Contact(wa_id="59170000984", phone_e164="+59170000984")
    session.add_all([first, second])
    await session.commit()

    await funnel.track(session, "search", contact=first, query="lavadora")
    await funnel.track(session, "search", contact=first, query="lavadora lg")
    await funnel.track(session, "search", contact=second, query="taladro")
    await session.commit()

    data = await funnel.stats(session, 30)
    search = next(row for row in data["steps"] if row["step"] == "search")

    assert search["contacts"] == 2
    assert search["events"] == 3
