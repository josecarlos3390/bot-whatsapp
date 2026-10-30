"""Asistente para crear configuración conversando (sin escribir en la base)."""

from __future__ import annotations

import pytest

from app.services import admin_assistant


class _Contenido:
    def __init__(self, texto: str) -> None:
        self.content = texto


class _Eleccion:
    def __init__(self, texto: str) -> None:
        self.message = _Contenido(texto)


class _Respuesta:
    def __init__(self, texto: str) -> None:
        self.choices = [_Eleccion(texto)]
        self.usage = None


class _FakeCompletions:
    def __init__(self, texto: str) -> None:
        self.texto = texto
        self.prompts: list[str] = []

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return _Respuesta(self.texto)


class _FakeLLM:
    def __init__(self, texto: str) -> None:
        self.chat = type(
            "C", (), {"completions": _FakeCompletions(texto)}
        )()


class _Agente:
    def __init__(self, texto: str) -> None:
        self._fake = _FakeLLM(texto)

    def _llm(self):
        return self._fake


def test_parsea_un_borrador_completo():
    datos = admin_assistant.parsear(
        '{"borrador": {"name": "Priorizar ELECTROLUX", "area": "ecommerce",'
        ' "rule_type": "brand_priority", "condition": {"category": "cocinas"},'
        ' "action": {"brand": "ELECTROLUX"}, "priority": 90},'
        ' "faltantes": [], "preguntas": [],'
        ' "resumen": "Regla para priorizar ELECTROLUX en cocinas"}',
        "regla",
    )

    assert datos["listo"] is True
    assert datos["faltantes"] == []
    assert datos["borrador"]["action"]["brand"] == "ELECTROLUX"
    assert "ELECTROLUX" in datos["resumen"]


def test_pide_la_prioridad_cuando_falta():
    datos = admin_assistant.parsear(
        '{"borrador": {"name": "Priorizar ELECTROLUX", "area": "ecommerce",'
        ' "rule_type": "brand_priority", "condition": {"category": "cocinas"},'
        ' "action": {"brand": "ELECTROLUX"}},'
        ' "faltantes": ["priority"], "preguntas": [],'
        ' "resumen": "Regla para priorizar ELECTROLUX"}',
        "regla",
    )

    assert datos["listo"] is False
    assert datos["faltantes"] == ["priority"]
    assert any("priority" in pregunta for pregunta in datos["preguntas"])


def test_descarta_campos_desconocidos():
    datos = admin_assistant.parsear(
        '{"borrador": {"name": "X", "inventado": "no", "priority": 10},'
        ' "faltantes": [], "preguntas": [], "resumen": "x"}',
        "regla",
    )

    assert "inventado" not in datos["borrador"]


def test_rechaza_respuestas_invalidas():
    assert admin_assistant.parsear("no sé", "regla") is None
    assert admin_assistant.parsear("{}", "inexistente") is None


async def test_conversar_arma_el_prompt_con_la_conversacion():
    agente = _Agente(
        '{"borrador": {"title": "Garantía"}, "faltantes": ["tags", "content"],'
        ' "preguntas": ["¿Qué etiquetas usa?"], "resumen": "Artículo"}'
    )

    resultado = await admin_assistant.conversar(
        agente,
        "conocimiento",
        [{"role": "user", "content": "quiero documentar la garantía"}],
    )

    assert resultado["tipo"] == "conocimiento"
    assert "tags" in resultado["faltantes"]
    prompt = agente._fake.chat.completions.prompts[0]
    assert "documentar la garantía" in prompt


async def test_conversar_con_tipo_desconocido_no_llama():
    agente = _Agente("{}")

    assert await admin_assistant.conversar(agente, "inventado", []) is None


def test_slug_sin_acentos():
    assert admin_assistant.slug("Garantía de heladeras") == "garantia-de-heladeras"
