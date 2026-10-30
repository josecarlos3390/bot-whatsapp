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


def test_quita_el_encabezado_repetido_del_listado():
    mensajes = [
        Outbound(text="Para *limpiar casa* tengo esto que puede servirte:"),
        Outbound(
            text=(
                "Encontré *3 opciones* 🛍️:\n\n"
                "1. Aspiradora 1,5L — Bs 1.399\n"
                "2. Aspiradora 2,8L — Bs 2.379"
            )
        ),
        _lista(),
    ]

    podados = closings.podar(mensajes)
    textos = [m.text or "" for m in podados]

    assert not any("Encontré" in texto for texto in textos)
    assert any("1. Aspiradora" in texto for texto in textos)


def test_conserva_el_encabezado_si_no_hay_otro():
    mensajes = [
        Outbound(text="Encontré *2 opciones* 🛍️:\n\n1. Sofá\n2. Mesa"),
        _lista(),
    ]

    podados = closings.podar(mensajes)

    assert "Encontré" in (podados[0].text or "")


def test_los_emojis_se_quitan_en_temas_delicados():
    from app.services import emoji_policy

    assert emoji_policy.es_delicado("me llegó roto el pedido")
    assert emoji_policy.es_delicado("quiero una devolución")
    assert not emoji_policy.es_delicado("busco un taladro")


def test_limpiar_deja_el_texto_sin_emojis():
    from app.services import emoji_policy

    limpio = emoji_policy.limpiar("¡Hola! 👋 ¿Qué buscás? 🛍️")

    assert "👋" not in limpio and "🛍️" not in limpio
    assert "Hola" in limpio and "buscás" in limpio

async def test_el_aviso_de_demora_llega_una_vez(session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "slow_reply_seconds", 0.05)
    contestados: list[str] = []

    class _Wa:
        async def send_text(self, wa_id, texto):
            contestados.append(texto)
            return "wamid.aviso"

    from app.services import ingest

    monkeypatch.setattr(ingest, "whatsapp", _Wa(), raising=False)
    await ingest._avisar_si_tarda("59170000001", True)

    assert contestados == ["Dame un segundo, estoy buscando 🔎"]


async def test_sin_delivery_no_avisa(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "slow_reply_seconds", 0.01)
    contestados: list[str] = []

    class _Wa:
        async def send_text(self, wa_id, texto):
            contestados.append(texto)
            return "wamid.aviso"

    from app.services import ingest

    monkeypatch.setattr(ingest, "whatsapp", _Wa(), raising=False)
    await ingest._avisar_si_tarda("59170000002", False)

    assert contestados == []