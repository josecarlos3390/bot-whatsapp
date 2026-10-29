"""Un mensaje, una pregunta: poda de cierres repetidos."""

from __future__ import annotations

from app.services import closings
from app.whatsapp import Outbound


def _lista() -> Outbound:
    return Outbound(
        kind="list",
        text="¿Cuál te interesa? 👀",
        button_text="Ver opciones",
        sections=[
            {
                "title": "Opciones",
                "rows": [{"id": "product:A", "title": "1. Taza"}],
            }
        ],
    )


def test_quita_el_cierre_generico_despues_de_la_lista():
    mensajes = [
        Outbound(text="Veo tu foto: parece taza."),
        Outbound(text="Encontré 3 opciones…"),
        _lista(),
        Outbound(
            kind="buttons",
            text="¿Te muestro el detalle de alguno o buscamos otra cosa?",
            buttons=[
                {"id": "catalog", "title": "Ver categorías"},
                {"id": "human", "title": "Asesor"},
            ],
        ),
    ]

    podados = closings.podar(mensajes)

    assert len(podados) == 3
    assert podados[-1].kind == "list"


def test_quita_la_pregunta_repetida_en_texto():
    mensajes = [
        Outbound(text="Encontré 2 opciones…"),
        _lista(),
        Outbound(text="¿Te muestro el detalle de alguno o buscamos otra cosa?"),
    ]

    assert len(closings.podar(mensajes)) == 2


def test_conserva_las_preguntas_obligatorias():
    mensajes = [
        Outbound(text="Encontré 2 opciones…"),
        _lista(),
        Outbound(text="Para asesorarte mejor: ¿Cuántos litros necesitás?"),
    ]

    podados = closings.podar(mensajes)

    assert len(podados) == 3
    assert "litros" in (podados[-1].text or "")


def test_no_toca_una_respuesta_normal():
    mensajes = [
        Outbound(text="Tenemos 26 opciones de heladeras."),
        Outbound(
            kind="buttons",
            text="¿Alguna marca en particular?",
            buttons=[{"id": "refine:Samsung", "title": "Samsung"}],
        ),
    ]

    assert len(closings.podar(mensajes)) == 2


def test_quita_textos_identicos_seguidos():
    mensajes = [Outbound(text="Hola"), Outbound(text="Hola")]

    assert len(closings.podar(mensajes)) == 1
