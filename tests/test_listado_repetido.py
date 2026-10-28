"""No repetir el mismo listado de productos."""

from __future__ import annotations

from app.models import Contact, Conversation, ConversationState
from app.services import repeat_guard
from app.whatsapp import Outbound


class _Reply:
    def __init__(self, messages):
        self.messages = messages


def _lista_con(skus: list[str]) -> _Reply:
    return _Reply(
        [
            Outbound(
                kind="list",
                text="Opciones:",
                sections=[
                    {
                        "title": "Opciones",
                        "rows": [
                            {"id": f"product:{sku}", "title": sku}
                            for sku in skus
                        ],
                    }
                ],
            )
        ]
    )


def test_extrae_los_skus_de_la_respuesta():
    reply = _lista_con(["A-1", "B-2"])

    assert repeat_guard.skus_de(reply) == ["A-1", "B-2"]


def test_detecta_el_mismo_listado():
    assert (
        repeat_guard.repite_el_mismo_listado(["A-1", "B-2"], ["B-2", "A-1"])
        is True
    )


def test_un_listado_distinto_no_es_repeticion():
    assert (
        repeat_guard.repite_el_mismo_listado(["A-1", "B-2"], ["C-3"]) is False
    )


def test_sin_listado_previo_no_hay_repeticion():
    assert repeat_guard.repite_el_mismo_listado([], ["A-1"]) is False


async def test_el_estado_recuerda_los_skus(session):
    contacto = Contact(wa_id="59170025001", phone_e164="+59170025001")
    session.add(contacto)
    await session.flush()
    conversacion = Conversation(contact_id=contacto.id)
    session.add(conversacion)
    await session.flush()
    estado = ConversationState(conversation_id=conversacion.id, shown_skus=[])
    session.add(estado)
    await session.commit()

    estado.shown_skus = ["A-1"]
    await session.commit()

    guardado = await session.get(ConversationState, estado.id)
    assert guardado.shown_skus == ["A-1"]


def test_detecta_repeticion_parcial():
    anteriores = ["A-1", "B-2", "C-3"]
    actuales = ["A-1", "B-2", "D-4"]

    assert repeat_guard.repite_parcial(anteriores, actuales) is True


def test_un_listado_nuevo_no_es_repeticion_parcial():
    assert (
        repeat_guard.repite_parcial(["A-1", "B-2"], ["C-3", "D-4"]) is False
    )


def test_listados_cortos_no_cuentan_como_parcial():
    assert repeat_guard.repite_parcial(["A-1"], ["A-1"]) is False


def test_el_filtro_sugerido_ofrece_salida():
    texto = repeat_guard.filtro_sugerido(Contact(wa_id="1", name="Ana"))

    assert "Ana" in texto
    assert "medida" in texto