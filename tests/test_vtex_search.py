"""Búsqueda libre con sinónimos de VTEX."""

from __future__ import annotations

import pytest

from app.config import settings
from app.models import CatalogItem
from app.services import catalog, vtex_search


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "vtex_search_enabled", True)
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.local")
    monkeypatch.setattr(settings, "sap_paas_api_key", "llave")
    monkeypatch.setattr(settings, "sap_paas_tenant", "RETAIL_QA5")
    vtex_search.olvidar()


async def _catalogo(session):
    datos = [
        ("PULV-1", "Pulverizador 5L Manual"),
        ("MUN-1", "Muñeca Bebe Princesas"),
        ("TAL-1", "Taladro Percutor 13mm"),
        ("TAL-2", "Taladro Inalambrico 12V"),
        ("TAL-3", "Taladro Atlas 500W"),
    ]
    for sku, nombre in datos:
        session.add(
            CatalogItem(
                sku=sku,
                name=nombre,
                price="100",
                stock=5,
                brand="TEST",
                category="Herramientas",
                active=True,
            )
        )
    await session.commit()


async def test_usa_los_sinonimos_cuando_el_local_no_alcanza(
    session, monkeypatch
):
    await _catalogo(session)

    async def _buscar(consulta, limite=8):
        assert consulta == "fumigador"
        return [
            {"sku": "PULV-1", "name": "Pulverizador 5L Manual"},
            {"sku": "NO-EXISTE", "name": "Otro"},
        ]

    monkeypatch.setattr(vtex_search, "buscar", _buscar)

    filas = await catalog.buscar_con_sinonimos(session, "fumigador", limit=8)

    assert [fila.sku for fila in filas] == ["PULV-1"]


async def test_ignora_skus_que_no_estan_en_el_catalogo(session, monkeypatch):
    await _catalogo(session)

    async def _buscar(consulta, limite=8):
        return [{"sku": "EXTERNO-9", "name": "No sincronizado"}]

    monkeypatch.setattr(vtex_search, "buscar", _buscar)

    assert await catalog.buscar_con_sinonimos(session, "bebote", limit=8) == []


async def test_si_el_local_alcanza_no_consulta_vtex(session, monkeypatch):
    await _catalogo(session)
    llamado = {"veces": 0}

    async def _buscar(consulta, limite=8):
        llamado["veces"] += 1
        return []

    monkeypatch.setattr(vtex_search, "buscar", _buscar)

    filas = await catalog.buscar_con_sinonimos(session, "taladro", limit=8)

    assert len(filas) >= 3
    assert llamado["veces"] == 0


async def test_sin_endpoint_no_rompe(monkeypatch):
    """Si /api/vtex/search no existe, el bot sigue con su catálogo."""

    class _Respuesta:
        status_code = 404

    async def _get(*args, **kwargs):
        return _Respuesta()

    monkeypatch.setattr("httpx.AsyncClient.get", _get, raising=False)

    assert await vtex_search.buscar("fumigador") == []
    # Queda marcado para no insistir en cada mensaje.
    assert not vtex_search.disponible()


def test_normaliza_la_respuesta():
    fila = vtex_search.normalizar(
        {
            "sku": "PULV-1",
            "sku_id": "5031",
            "name": "Pulverizador",
            "price": 165.0,
            "stock": 4,
        }
    )

    assert fila["sku"] == "PULV-1"
    assert fila["sku_id"] == "5031"
    assert fila["currency"] == "BOB"
