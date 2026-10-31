"""Cliente que pide una persona o insiste."""

from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.models import Contact, Conversation
from app.services import ingest, insistencia


def test_detecta_el_pedido_explicito():
    for texto in (
        "quiero hablar con una persona",
        "no quiero hablar con un bot",
        "atendeme vos",
        "pasame con un asesor",
        "necesito un humano",
    ):
        assert insistencia.pide_humano(texto), texto


def test_no_confunde_una_consulta_normal():
    assert not insistencia.pide_humano("busco un sofá")
    assert not insistencia.pide_humano("¿tienen stock de lavadoras?")


def test_detecta_la_insistencia_corta():
    assert insistencia.insiste("hola?")
    assert insistencia.insiste("sigue ahi")
    assert insistencia.insiste("hay alguien")
    assert not insistencia.insiste("quiero un colchón de 2 plazas")


async def test_el_cliente_insistente_recibe_un_aviso(session):
    """Pide un asesor y escribe: no queda en silencio para siempre."""
    numero = f"5917{uuid.uuid4().hex[:8]}"
    mensajes = []
    for indice in range(6):
        texto = "quiero hablar con una persona" if indice == 0 else "hola?"
        salida = await ingest.ingest_inbound(
            session,
            numero,
            texto,
            f"wamid.{uuid.uuid4().hex[:10]}",
            name="Kari",
            deliver=False,
        )
        mensajes.append(
            " ".join(getattr(m, "text", "") or "" for m in salida)
        )

    juntos = " ".join(mensajes).lower()
    assert "gracias por la paciencia" in juntos
    assert "seguimos con tu caso" in juntos


async def test_el_bot_queda_en_silencio_al_principio(session):
    numero = f"5917{uuid.uuid4().hex[:8]}"
    await ingest.ingest_inbound(
        session,
        numero,
        "quiero hablar con una persona",
        f"wamid.{uuid.uuid4().hex[:10]}",
        name="Kari",
        deliver=False,
    )
    salida = await ingest.ingest_inbound(
        session,
        numero,
        "hola?",
        f"wamid.{uuid.uuid4().hex[:10]}",
        name="Kari",
        deliver=False,
    )

    assert salida == []


async def test_sin_handoff_el_bot_atiende_normal(session):
    numero = f"5917{uuid.uuid4().hex[:8]}"
    contacto = Contact(wa_id=numero, phone_e164=f"+{numero}", name="Ana")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    assert await insistencia.esperando(session, contacto) == 0
