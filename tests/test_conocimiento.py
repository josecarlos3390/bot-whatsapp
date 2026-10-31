"""La base de conocimiento no debe mostrar avisos internos al cliente."""

from __future__ import annotations

from pathlib import Path

import pytest

CARPETA = Path("knowledge")
AVISOS = (
    "contenido de ejemplo",
    "valores de ejemplo",
    "reemplazar por",
)


def _articulos():
    return [
        archivo
        for archivo in sorted(CARPETA.glob("*.md"))
        if not archivo.name.lower().startswith("readme")
    ]


@pytest.mark.parametrize("archivo", _articulos(), ids=lambda a: a.stem)
def test_ningun_articulo_muestra_avisos_internos(archivo):
    texto = archivo.read_text(encoding="utf-8").lower()

    for aviso in AVISOS:
        assert aviso not in texto, f"{archivo.name} muestra «{aviso}»"


@pytest.mark.parametrize("archivo", _articulos(), ids=lambda a: a.stem)
def test_todos_los_articulos_son_publicados(archivo):
    texto = archivo.read_text(encoding="utf-8")

    assert "status: published" in texto
