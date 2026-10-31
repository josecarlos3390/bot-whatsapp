"""Productos afines cuando no hay lo que el cliente pide."""

from __future__ import annotations

from app.services import familia


def test_monitor_sugiere_televisores():
    terminos = familia.terminos("monitor")

    assert "televisor" in terminos
    assert "monitor" not in terminos


def test_impresora_no_sugiere_pintura():
    # "Tinta" en este catálogo es pintura, no insumo de impresora.
    assert familia.terminos("impresora") == ()


def test_un_objeto_desconocido_no_inventa():
    assert familia.terminos("telescopio") == ()


def test_la_categoria_generica_no_sirve_para_sugerir():
    from app.flows.media import _categoria_util

    assert not _categoria_util("electrónica")
    assert not _categoria_util("Electronica")
    assert not _categoria_util("otros")
    assert _categoria_util("Monitores")
    assert _categoria_util("Soportes para TV")


def test_una_ducha_no_coincide_con_un_monitor():
    from app.flows.media import _coincide

    descripcion = {
        "objeto": "monitor",
        "categoria": "electrónica",
        "marca": "Samsung",
        "atributos": "pantalla plana 24 pulgadas",
    }
    ducha = {"name": "Gran Ducha Electrónica 7000W Blanca", "category": "Duchas"}

    assert not _coincide(descripcion, ducha)


def test_detecta_la_palabra_ambigua():
    from app.services import homonimos

    assert homonimos.buscar("busco una consola")["palabra"] == "consola"
    assert homonimos.buscar("quiero tinta para la pared")["palabra"] == "tinta"
    assert homonimos.buscar("busco un taladro") is None


def test_no_pregunta_si_el_cliente_aclaro():
    from app.services import homonimos

    assert homonimos.ya_aclaro("una consola para jugar", "consola")
    assert homonimos.ya_aclaro("el mueble consola para la sala", "consola")
    assert not homonimos.ya_aclaro("busco una consola", "consola")


async def test_solo_hay_muebles_de_consola(session):
    from app.services import homonimos

    significado = await homonimos.significado(session, "consola")

    assert significado in {"a", "ninguno"}


def test_la_aclaracion_ofrece_los_dos_significados():
    from app.services import homonimos

    aclaracion = homonimos.aclarar("consola", "a")

    assert "videojuegos" in aclaracion["texto"].lower()
    titulos = [boton["title"] for boton in aclaracion["botones"]]
    assert "mueble" in titulos
    assert all(boton["id"].startswith("find:") for boton in aclaracion["botones"])