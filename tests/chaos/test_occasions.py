"""CRUD y resolución de ocasiones administrables."""

from __future__ import annotations

from app.models import Contact
from app.services import occasion_store
from sqlalchemy import select


async def test_crear_publicar_y_resolver_ocasion(session):
    row = await occasion_store.create_occasion(
        session,
        name="Prueba ocasional",
        aliases=["prueba ocasional", "pruebaocasional"],
        direct=["filtro"],
        exclude=["mueble"],
        exclude_categories=["MUEBLES"],
        bridges=[{"label": "alternativa", "terms": ["aceite"]}],
        area="marketing",
        status="draft",
        priority=100,
        changed_by="test",
    )
    assert row.status == "draft"
    key, event = await occasion_store.resolve(
        session, "tienes algo para pruebaocasional"
    )
    assert key is None  # borrador no se resuelve
    await occasion_store.publish_occasion(session, row, changed_by="test")
    key, event = await occasion_store.resolve(
        session, "tienes algo para pruebaocasional"
    )
    assert key == "prueba-ocasional"
    assert event["direct"] == ["filtro"]
    await occasion_store.delete_occasion(session, row)


async def test_seed_no_duplica(session):
    first = await occasion_store.seed_examples(session)
    second = await occasion_store.seed_examples(session)
    assert first >= 10
    assert second == 0
    rows = await occasion_store.list_occasions(session)
    assert rows
    assert all(row.status == "published" for row in rows)
