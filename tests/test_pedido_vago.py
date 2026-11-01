"""Pedidos vagos y cuestionamientos de lo que muestra el bot."""

from __future__ import annotations

from app.services import pedido_vago


def test_detecta_un_pedido_vago():
    for texto in (
        "algo para mi",
        "algo para mí",
        "sorprendeme",
        "vende algo",
        "algo lindo",
        "nada interesante",
    ):
        assert pedido_vago.es_vago(texto), texto


def test_una_busqueda_normal_no_es_vaga():
    assert not pedido_vago.es_vago("busco un colchón de 2 plazas")
    assert not pedido_vago.es_vago("quiero una licuadora")


def test_detecta_el_cuestionamiento():
    for texto in (
        "¿por qué me sugerís almohadas?",
        "y porque me sugieres almohadas?",
        "por qué me mostraste eso",
        "no te pedí eso",
        "qué tiene que ver con lo que busco",
    ):
        assert pedido_vago.es_cuestionamiento(texto), texto


def test_una_consulta_normal_no_es_cuestionamiento():
    assert not pedido_vago.es_cuestionamiento("busco un sofá")
    assert not pedido_vago.es_cuestionamiento("¿cuánto sale el envío?")


def test_pide_ver_ofertas():
    for texto in (
        "no tenés nada interesante? vendeme algo",
        "mostrame algo",
        "qué tenés de bueno",
        "algo en descuento",
    ):
        assert pedido_vago.quiere_ver_ofertas(texto), texto


def test_algo_para_mi_no_pide_ofertas_sino_pregunta():
    assert not pedido_vago.quiere_ver_ofertas("algo para mi")
    assert pedido_vago.es_vago("algo para mi")


async def test_las_ofertas_se_diversifican_por_rubro(session):
    from app.models import CatalogItem, ProductPromotion
    from app.services import catalog as catalogo

    for indice in range(4):
        session.add(
            CatalogItem(
                sku=f"OF-{indice}",
                name=f"Cubrecama {indice}",
                price="1000",
                stock=5,
                category="Cubrecamas",
                active=True,
            )
        )
    session.add(
        CatalogItem(
            sku="OF-OTRO",
            name="Taladro oferta",
            price="1000",
            stock=5,
            category="Herramientas",
            active=True,
        )
    )
    await session.commit()
    for indice in range(4):
        session.add(
            ProductPromotion(
                sku=f"OF-{indice}",
                price_list="1",
                price="500",
                discount_percent="50",
            )
        )
    session.add(
        ProductPromotion(
            sku="OF-OTRO", price_list="1", price="600", discount_percent="40"
        )
    )
    await session.commit()

    filas = await catalogo.best_discounts(session, limit=5)
    cubrecamas = [
        fila for fila in filas if (fila.category or "").lower() == "cubrecamas"
    ]

    assert len(cubrecamas) <= 2


def test_el_emoji_no_ensucia_listados_ni_tono_serio():
    from app.services import emoji_policy

    listado = "1. Aire 12000 — Bs 3.999\n2. Aire 18000 — Bs 8.579"
    assert emoji_policy.adornar(listado) == listado

    disculpa = "Tenés razón y te pido disculpas: no era lo que pediste."
    assert emoji_policy.adornar(disculpa) == disculpa


def test_el_emoji_se_suma_en_una_respuesta_seca():
    from app.services import emoji_policy

    texto = "Sí, tenemos aires acondicionados. ¿Para qué ambiente lo buscás?"

    assert emoji_policy.adornar(texto) != texto
