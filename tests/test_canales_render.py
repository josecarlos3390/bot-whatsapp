"""Render por canal: listas, botones y formato."""

from __future__ import annotations

from app.channels import INSTAGRAM, MESSENGER, WEBCHAT, WHATSAPP
from app.channels.render import render, render_reply
from app.whatsapp import Outbound


def _lista() -> Outbound:
    return Outbound(
        kind="list",
        text="¿Por dónde arrancamos? Elegí una categoría 👇",
        button_text="Ver categorías",
        sections=[
            {
                "title": "Ambientes",
                "rows": [
                    {"id": "cat:sala", "title": "Sala y comedor", "description": "Sofás, mesas"},
                    {"id": "cat:dormitorio", "title": "Dormitorio", "description": "Camas, colchones"},
                ],
            }
        ],
    )


def test_whatsapp_recibe_la_lista_como_lista():
    salida = render(_lista(), WHATSAPP)

    assert len(salida) == 1
    assert salida[0].kind == "list"
    assert len(salida[0].rows) == 2


def test_instagram_recibe_las_opciones_numeradas():
    salida = render(_lista(), INSTAGRAM)

    assert salida[0].kind == "text"
    assert "1. Sala y comedor" in salida[0].text
    assert "2. Dormitorio" in salida[0].text
    assert "número" in salida[0].text


def test_messenger_quita_los_asteriscos():
    mensaje = Outbound(kind="text", text="Tenemos *3 opciones* de sofá")
    salida = render(mensaje, MESSENGER)

    assert salida[0].text == "Tenemos 3 opciones de sofá"


def test_webchat_conserva_el_markdown():
    mensaje = Outbound(kind="text", text="Tenemos *3 opciones* de sofá")
    salida = render(mensaje, WEBCHAT)

    assert "*3 opciones*" in salida[0].text


def test_los_botones_que_sobran_van_como_texto():
    mensaje = Outbound(
        kind="buttons",
        text="¿Qué buscás?",
        buttons=[
            {"id": "a", "title": "Uno"},
            {"id": "b", "title": "Dos"},
            {"id": "c", "title": "Tres"},
        ],
    )
    salida = render(mensaje, INSTAGRAM)

    assert salida[0].kind == "buttons"
    assert len(salida[0].buttons) == 3

    web = render(
        Outbound(
            kind="buttons",
            text="¿Qué buscás?",
            buttons=[{"id": str(i), "title": f"Opción {i}"} for i in range(6)],
        ),
        WEBCHAT,
    )
    assert len(web[0].buttons) == 6


def test_canal_sin_botones_los_pasa_a_texto():
    from app.channels import Capabilities

    plano = Capabilities(name="sms", buttons=0, lists=False, markdown="plain")
    mensaje = Outbound(
        kind="buttons",
        text="¿Seguimos?",
        buttons=[{"id": "si", "title": "Sí"}, {"id": "no", "title": "No"}],
    )
    salida = render(mensaje, plano)

    assert salida[0].kind == "text"
    assert "1. Sí" in salida[0].text


def test_imagen_sin_soporte_se_convierte_en_texto():
    from app.channels import Capabilities

    sin_imagen = Capabilities(name="sms", images=False, buttons=0, lists=False)
    mensaje = Outbound(kind="image", text="TV 32 pulgadas", url="https://x/y.png")
    salida = render(mensaje, sin_imagen)

    assert salida[0].kind == "text"
    assert "TV 32" in salida[0].text


def test_render_respuesta_completa():
    from app.agent import AgentReply

    reply = AgentReply([_lista(), Outbound(kind="text", text="Listo")])
    salida = render_reply(reply, INSTAGRAM)

    assert len(salida) == 2
    assert all(item.kind == "text" for item in salida)
