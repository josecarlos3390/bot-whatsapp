"""El asistente crea la configuración de verdad (regla, ocasión, artículo)."""

from __future__ import annotations

import httpx
import pytest

from app import api_knowledge
from app.config import settings
from app.db import get_session
from app.main import app
from app.services import area_rules, occasion_store


@pytest.fixture(autouse=True)
def _entorno(tmp_path, monkeypatch):
    carpeta = tmp_path / "knowledge"
    carpeta.mkdir()
    monkeypatch.setattr(api_knowledge, "CARPETA", carpeta)
    monkeypatch.setattr(settings, "admin_token", "clave-admin")
    yield carpeta


def _cliente(session) -> httpx.AsyncClient:
    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"x-admin-token": "clave-admin"},
    )


async def test_crea_una_regla_y_el_bot_la_usa(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/assistant/crear",
            json={
                "tipo": "regla",
                "borrador": {
                    "name": "Priorizar ELECTROLUX en cocinas",
                    "area": "ecommerce",
                    "rule_type": "brand_priority",
                    "condition": {"category": "cocinas"},
                    "action": {"brand": "ELECTROLUX"},
                    "priority": 90,
                    "status": "published",
                },
            },
        )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["ok"] is True
    assert datos["estado"] == "published"

    # La regla existe y queda activa para el bot.
    activas = await area_rules.active_rules(session, area="ecommerce")
    assert any(regla.name == "Priorizar ELECTROLUX en cocinas" for regla in activas)


async def test_crea_una_ocasion(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/assistant/crear",
            json={
                "tipo": "ocasion",
                "borrador": {
                    "name": "Día del Padre",
                    "direct": ["taladro", "set de herramientas"],
                    "priority": 80,
                    "status": "published",
                },
            },
        )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["tipo"] == "ocasion"
    filas = await occasion_store.list_occasions(session)
    assert any(fila.name == "Día del Padre" for fila in filas)


async def test_crea_un_articulo_de_conocimiento(session, _entorno):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/assistant/crear",
            json={
                "tipo": "conocimiento",
                "borrador": {
                    "title": "Garantía de colchones",
                    "tags": "garantia, colchon",
                    "content": "- Cubre 12 meses por falla de fábrica.\n"
                    "- Se gestiona con la factura de compra.\n",
                },
            },
        )

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["slug"] == "garantia-de-colchones"
    assert (_entorno / "garantia-de-colchones.md").exists()


async def test_no_crea_si_faltan_datos(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/assistant/crear",
            json={
                "tipo": "regla",
                "borrador": {
                    "name": "Sin prioridad",
                    "area": "ecommerce",
                    "rule_type": "brand_priority",
                    "condition": {"category": "cocinas"},
                    "action": {"brand": "X"},
                },
            },
        )

    assert respuesta.status_code == 400
    assert "priority" in respuesta.json()["detail"]


async def test_un_tipo_invalido_no_crea(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/assistant/crear",
            json={"tipo": "inventado", "borrador": {"x": 1}},
        )

    assert respuesta.status_code == 400
