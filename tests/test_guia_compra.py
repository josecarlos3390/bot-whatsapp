"""Guía de compra: preguntar el dato que falta para recomendar bien."""

from __future__ import annotations

import pytest

from app.services import tech_guide


def test_reconoce_el_rubro_por_palabras():
    assert tech_guide.rubro("busco un aire acondicionado") == "aire acondicionado"
    assert tech_guide.rubro("quiero una heladera") == "heladera"
    assert tech_guide.rubro("necesito una lavadora") == "lavadora"
    assert tech_guide.rubro("busco una tele") == "televisor"
    assert tech_guide.rubro("busco un taladro") == ""


def test_pregunta_los_metros_del_aire():
    falta = tech_guide.falta_dato("busco un aire acondicionado")

    assert falta is not None
    assert falta["clave"] == "m2"
    assert "metros" in falta["pregunta"].lower()


def test_no_pregunta_si_el_cliente_ya_dijo_los_metros():
    assert tech_guide.falta_dato("busco un aire para 20 m2") is None
    assert tech_guide.falta_dato("un split para 18 metros") is None


def test_pregunta_las_personas_de_la_heladera():
    falta = tech_guide.falta_dato("quiero una heladera")

    assert falta is not None
    assert falta["clave"] == "personas"


def test_no_pregunta_si_ya_dijo_cuantos_son():
    assert tech_guide.falta_dato("somos 4 en casa, quiero una heladera") is None


def test_los_botones_llevan_la_medida():
    falta = tech_guide.falta_dato("busco un aire acondicionado")
    botones = tech_guide.opciones_botones(falta)

    assert len(botones) == 3
    assert botones[0]["id"].startswith("uso:aire acondicionado")
    assert "9000 BTU" in botones[0]["id"]


def test_un_rubro_sin_guia_no_pregunta():
    assert tech_guide.falta_dato("busco un taladro") is None


@pytest.mark.parametrize(
    "texto,clave",
    [
        ("busco una pintura", "m2"),
        ("quiero un colchon", "plazas"),
        ("necesito un ventilador", "m2"),
        ("quiero cortinas", "ancho"),
    ],
)
def test_mas_rubros_preguntan_su_dato(texto, clave):
    falta = tech_guide.falta_dato(texto)

    assert falta is not None
    assert falta["clave"] == clave


def test_la_parrilla_la_maneja_la_ocasion_del_portal():
    assert tech_guide.falta_dato("busco una parrilla") is None


def test_la_guia_del_conocimiento_tiene_todos_los_rubros():
    from pathlib import Path

    texto = Path("knowledge/guia-compra.md").read_text(encoding="utf-8").lower()
    for rubro in ("aire", "heladera", "lavadora", "televisor", "colchón", "pintura", "ventilador", "cortina"):
        assert rubro in texto