"""Lectura del mensaje con IA (NLU primero), medida contra las reglas."""

from __future__ import annotations

from app.services import nlu


def test_arma_la_consulta_con_producto_y_atributos():
    lectura = {
        "intencion": "producto",
        "producto": "colchón",
        "atributos": ["2 plazas", "firme"],
    }

    assert nlu.consulta(lectura) == "colchón 2 plazas firme"


def test_sin_atributos_usa_solo_el_producto():
    assert nlu.consulta({"producto": "taladro"}) == "taladro"


def test_sin_lectura_no_hay_consulta():
    assert nlu.consulta(None) == ""


def test_es_busqueda_para_producto_y_precio():
    assert nlu.es_busqueda({"intencion": "producto", "producto": "taladro"})
    assert nlu.es_busqueda({"intencion": "precio", "producto": "heladera"})


def test_no_es_busqueda_sin_producto():
    assert not nlu.es_busqueda({"intencion": "producto", "producto": ""})
    assert not nlu.es_busqueda({"intencion": "envio", "producto": None})
    assert not nlu.es_busqueda(None)


def test_un_saludo_con_producto_sigue_siendo_busqueda():
    assert nlu.es_busqueda({"intencion": "saludo", "producto": "colchones"})
