"""Notas de voz: transcripción local (OpenAI no es alcanzable desde acá)."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services import transcription


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setattr(transcription, "_fallos_openai", 0)
    monkeypatch.setattr(transcription, "_openai_hasta", 0.0)


def test_elige_openai_cuando_hay_clave(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", True)
    monkeypatch.setattr(settings, "transcribe_backend", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "sk-prueba")

    assert transcription.motor() == "openai"


def test_usa_local_si_no_hay_clave(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", True)
    monkeypatch.setattr(settings, "transcribe_backend", "auto")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(transcription, "disponible", lambda: True)

    assert transcription.motor() == "local"


def test_apagado_no_usa_ninguno(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", False)

    assert transcription.motor() == "ninguno"


def test_backend_local_ignora_la_clave(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", True)
    monkeypatch.setattr(settings, "transcribe_backend", "local")
    monkeypatch.setattr(settings, "openai_api_key", "sk-prueba")
    monkeypatch.setattr(transcription, "disponible", lambda: True)

    assert transcription.motor() == "local"


async def test_sin_motor_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", False)

    assert await transcription.transcribir(b"audio", "audio/ogg") == ""


async def test_el_audio_muy_corto_no_se_transcribe(monkeypatch):
    monkeypatch.setattr(settings, "transcribe_enabled", True)
    monkeypatch.setattr(transcription, "disponible", lambda: True)

    assert await transcription.transcribir(b"\x00\x01", "audio/ogg") == ""


def test_parsea_el_resultado_de_openai(monkeypatch):
    import asyncio

    class Respuesta:
        status_code = 200

        def json(self):
            return {"text": "  busco un colchón  "}

    class Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Respuesta()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: Cliente())
    monkeypatch.setattr(settings, "openai_api_key", "sk-prueba")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/")

    texto = asyncio.run(
        transcription._transcribir_openai(b"audio", "audio/ogg")
    )

    assert texto == "busco un colchón"
