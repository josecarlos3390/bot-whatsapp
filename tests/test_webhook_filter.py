"""Webhook: solo se procesan los mensajes del número configurado."""

from __future__ import annotations

from app.api import _iter_messages
from app.config import settings


def _payload(phone_number_id: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "contacts": [{"profile": {"name": "Ana"}}],
                            "messages": [
                                {
                                    "from": "59170000001",
                                    "id": "wamid.1",
                                    "type": "text",
                                    "text": {"body": "hola"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_procesa_el_numero_configurado(monkeypatch):
    monkeypatch.setattr(settings, "wa_phone_number_id", "111")

    mensajes = list(_iter_messages(_payload("111")))

    assert len(mensajes) == 1
    assert mensajes[0]["wa_id"] == "59170000001"


def test_ignora_otro_numero(monkeypatch):
    monkeypatch.setattr(settings, "wa_phone_number_id", "111")

    mensajes = list(_iter_messages(_payload("222")))

    assert mensajes == []


def test_sin_numero_configurado_procesa_todo(monkeypatch):
    monkeypatch.setattr(settings, "wa_phone_number_id", "")

    assert len(list(_iter_messages(_payload("222")))) == 1
