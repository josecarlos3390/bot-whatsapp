"""«¿En qué tienda lo encuentro?»: responder la disponibilidad real.

El stock es central: no hay stock separado por tienda. El bot no debe
prometer algo que no puede confirmar ni repetir la ficha del producto.
"""

from __future__ import annotations

from app.services import tienda


def test_detecta_la_pregunta_por_tienda():
    for texto in (
        "¿en qué tienda puedo encontrarlo?",
        "en que sucursal está",
        "dónde lo puedo retirar",
        "tienen stock en la tienda?",
        "quiero retiro en tienda",
    ):
        assert tienda.pregunta_tienda(texto), texto


def test_una_busqueda_normal_no_pregunta_por_tienda():
    assert not tienda.pregunta_tienda("busco un aire de 12000")
    assert not tienda.pregunta_tienda("¿cuánto sale el envío?")


def test_lista_las_tres_tiendas_con_direccion():
    tiendas = tienda.tiendas()

    assert len(tiendas) >= 3
    assert all("direccion" in local and local["direccion"] for local in tiendas)
    assert any("Banzer" in local["direccion"] for local in tiendas)


def test_no_muestra_cantidades_de_stock():
    texto = tienda.responder("Aire Lakes", 13)

    assert "13" not in texto
    assert "unidades" not in texto.lower()
    assert "banzer" in texto.lower()


def test_no_repite_la_ficha_del_producto():
    texto = tienda.responder("Aire Lakes", 13).lower()

    # Nada de precio ni descuento: eso ya lo mostró la ficha.
    assert "descuento" not in texto
    assert "precio de lista" not in texto
