"""Editor de la base de conocimiento: listar, crear, guardar y archivar."""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from app import api_knowledge
from app.api import router as api_router
from app.config import settings
from app.db import get_session
from app.main import app


@pytest.fixture(autouse=True)
def _carpeta_temporal(tmp_path, monkeypatch):
    carpeta = tmp_path / "knowledge"
    carpeta.mkdir()
    (carpeta / "envios.md").write_text(
        "---\ntitle: Envíos\nstatus: published\ntags: envio, entrega\n---\n\n"
        "- Entrega en 24 horas.\n- Retiro en tienda de lunes a sábado.\n"
        "- Cobertura en todo el país con costo según la zona.\n",
        encoding="utf-8",
    )
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


async def test_lista_los_articulos(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.get("/admin/knowledge-base")

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["total"] == 1
    assert datos["articulos"][0]["slug"] == "envios"


async def test_crea_un_articulo(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/knowledge-base",
            json={
                "title": "Garantía de heladeras",
                "status": "published",
                "tags": "garantia, heladera",
                "content": "- Cubre 12 meses por falla de fábrica.\n"
                "- Se gestiona con la factura de compra.\n",
            },
        )

    assert respuesta.status_code == 200
    assert respuesta.json()["slug"] == "garantia-de-heladeras"
    assert (api_knowledge.CARPETA / "garantia-de-heladeras.md").exists()


async def test_no_publica_sin_etiquetas(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/knowledge-base",
            json={
                "title": "Prueba sin tags",
                "status": "published",
                "tags": "",
                "content": "x" * 120,
            },
        )

    assert respuesta.status_code == 400
    assert "etiqueta" in respuesta.json()["detail"].lower()


async def test_no_publica_contenido_muy_corto(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.post(
            "/admin/knowledge-base",
            json={
                "title": "Prueba corta",
                "status": "published",
                "tags": "prueba",
                "content": "muy corto",
            },
        )

    assert respuesta.status_code == 400


async def test_guarda_cambios(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.put(
            "/admin/knowledge-base/envios",
            json={
                "title": "Envíos y entregas",
                "status": "published",
                "tags": "envio, entrega, retiro",
                "content": "- Entrega en 48 horas.\n- Retiro de lunes a sábado.\n",
            },
        )

    assert respuesta.status_code == 200
    assert respuesta.json()["title"] == "Envíos y entregas"


async def test_archiva_sin_borrar(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.delete("/admin/knowledge-base/envios")

    assert respuesta.status_code == 200
    assert respuesta.json()["archivado"] == "envios.md.archivado"
    assert not (api_knowledge.CARPETA / "envios.md").exists()
    assert (api_knowledge.CARPETA / "envios.md.archivado").exists()


async def test_rechaza_nombres_peligrosos(session):
    async with _cliente(session) as cliente:
        respuesta = await cliente.get("/admin/knowledge-base/../../etc/passwd")

    assert respuesta.status_code in {400, 404}


async def test_sin_token_no_entra(session):
    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as cliente:
        respuesta = await cliente.get("/admin/knowledge-base")

    assert respuesta.status_code == 401
