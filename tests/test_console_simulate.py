"""El panel puede probar al bot sin ensuciar datos reales."""

from __future__ import annotations

from sqlalchemy import func, select

from app.api import SimulateBotPayload, admin_simulate
from app.models import Contact, FunnelEvent


async def test_probar_el_bot_responde_y_no_deja_rastro(session):
    antes = await session.scalar(select(func.count()).select_from(Contact))

    resultado = await admin_simulate(
        SimulateBotPayload(text="hola, que tenes?"),
        _={"area": "ecommerce"},
        session=session,
    )

    assert resultado["ok"] is True
    assert resultado["replies"]
    assert resultado["ms"] > 0

    despues = await session.scalar(select(func.count()).select_from(Contact))
    assert despues == antes

    eventos = await session.scalar(
        select(func.count())
        .select_from(FunnelEvent)
        .where(FunnelEvent.contact_id.is_(None))
    )
    assert eventos == 0
