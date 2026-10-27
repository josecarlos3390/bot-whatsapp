"""Políticas de ejemplo: el bot responde y queda marcado que falta validar."""

from __future__ import annotations

from app.services import knowledge, readiness


def test_las_politicas_de_ejemplo_se_publican_y_se_marcan():
    knowledge.reload()
    articulos = {a.source: a for a in knowledge.load_articles()}

    for nombre in ("garantias.md", "pagos.md", "devoluciones.md"):
        articulo = articulos[nombre]
        assert articulo.status == "published"
        assert articulo.sample is True
        # Sin placeholders pendientes.
        assert "[verificar" not in articulo.content.lower()


def test_el_buscador_encuentra_garantias_y_pagos():
    knowledge.reload()

    assert knowledge.search("garantia de una lavadora", limit=1)
    assert knowledge.search("formas de pago", limit=1)
    assert knowledge.search("cuotas sin interes", limit=1)


async def test_el_semaforo_avisa_que_son_de_ejemplo(session):
    datos = await readiness.readiness(session)
    politicas = next(c for c in datos["criteria"] if c["key"] == "politicas")

    assert politicas["ok"] is True
    assert "ejemplo" in politicas["detail"]
