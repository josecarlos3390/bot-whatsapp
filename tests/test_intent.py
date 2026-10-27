"""Clasificador de intención: reglas, ambigüedad y frase personal."""

from __future__ import annotations

import json
from pathlib import Path

from app.agent import Agent
from app.models import Contact
from app.services import intent, occasions

CASOS = json.loads(
    (Path(__file__).parent / "data" / "intent_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


def test_reglas_aciertan_intencion():
    """Las reglas resuelven el 100% de los casos del set de referencia."""
    fallos = []
    for caso in CASOS:
        resultado = intent.rules(caso["text"])
        if resultado["intent"] != caso["intent"]:
            fallos.append((caso["text"], resultado["intent"], caso["intent"]))
    assert not fallos, fallos


def test_reglas_aciertan_compra_y_ambiguedad():
    fallos = []
    for caso in CASOS:
        resultado = intent.rules(caso["text"])
        if "buy" in caso and resultado["buy"] != caso["buy"]:
            fallos.append((caso["text"], "buy", resultado["buy"], caso["buy"]))
        if "ambiguous" in caso and resultado["ambiguous"] != caso["ambiguous"]:
            fallos.append(
                (caso["text"], "ambiguous", resultado["ambiguous"], caso["ambiguous"])
            )
    assert not fallos, fallos


def test_ocasion_detecta_tema_aunque_este_negado():
    assert occasions.detect("No, te cuento que ya viajaré") == "vacaciones"


async def test_frase_personal_pregunta_antes_de_asumir(session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000851", phone_e164="+59170000851")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(session, contact, "No, te cuento que ya viajaré")

    texto = " ".join(m.text or "" for m in reply.messages)
    botones = [
        button["id"]
        for message in reply.messages
        for button in (message.buttons or [])
    ]
    assert "para qué lo necesitás" in texto.lower() or "para que lo necesitas" in texto.lower()
    assert "sección específica" not in texto.lower()
    assert any(str(b).startswith("find:") for b in botones)


async def test_plan_de_viaje_claro_no_pregunta_y_ofrece(session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    contact = Contact(wa_id="59170000852", phone_e164="+59170000852")
    session.add(contact)
    await session.commit()

    reply = await Agent().handle(
        session, contact, "me voy de viaje la semana que viene"
    )

    texto = " ".join(m.text or "" for m in reply.messages)
    assert "vacaciones" in texto.lower() or "viaje" in texto.lower()
    assert "sección específica" not in texto.lower()
