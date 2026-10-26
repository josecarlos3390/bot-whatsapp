"""Clasificación por área y contexto de reglas para el agente."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaRule
from . import rules_engine


AREA_TERMS: dict[str, re.Pattern[str]] = {
    "calidad": re.compile(
        r"\b(devoluci[oó]n(?:es)?|devolver|garant[ií]as?|cambios?|reclamos?|"
        r"rotos?|rotas?|defectuosos?|reembolsos?|facturas?|comprobantes?)\b",
        re.IGNORECASE,
    ),
    "operaciones": re.compile(
        r"\b(env[ií]os?|entregas?|sucursales?|horarios?|retiros?|"
        r"direcci[oó]n(?:es)?|ubicaci[oó]n(?:es)?|domicilios?|despachos?)\b",
        re.IGNORECASE,
    ),
    "marketing": re.compile(
        r"\b(promoci[oó]n(?:es)?|promos?|ofertas?|descuentos?|"
        r"black|coupon|cup[oó]n(?:es)?)\b",
        re.IGNORECASE,
    ),
    "ecommerce": re.compile(
        r"\b(productos?|precios?|stock|marcas?|comprar|cat[aá]logo|"
        r"modelos?|televisor(?:es)?|heladeras?|lavadoras?|"
        r"colch[oó]n(?:es)?|aire(?:s)?|muebles?|pintura(?:s)?)\b",
        re.IGNORECASE,
    ),
}

AREA_ORDER = ("calidad", "operaciones", "marketing", "ecommerce")


def detect(text: str) -> list[str]:
    """Devuelve áreas probables, de mayor a menor prioridad."""
    found = [
        area for area in AREA_ORDER if AREA_TERMS[area].search(text or "")
    ]
    return found or ["general"]


def _rule_line(rule: AreaRule) -> str:
    action = rule.action or {}
    if rule.rule_type == "brand_priority":
        return (
            f"- Priorizar la marca {action.get('brand')} "
            f"(prioridad {rule.priority})."
        )
    if rule.rule_type == "promotion_priority":
        return (
            "- Priorizar productos con promoción vigente y stock "
            f"(descuento mínimo {action.get('min_discount', 0)}%)."
        )
    if rule.rule_type == "return_flow":
        questions = action.get("questions") or []
        return (
            f"- Flujo de devolución con {len(questions)} preguntas; "
            "usar las preguntas de la regla, no inventar."
        )
    if rule.rule_type == "response_rule":
        instruction = action.get("instruction") or action.get("text") or ""
        return f"- Instrucción de respuesta: {instruction}"
    if rule.rule_type == "required_questions":
        return "- Hay preguntas obligatorias definidas por el área."
    return f"- Regla {rule.rule_type} activa."


async def context_for(
    session: AsyncSession,
    text: str,
    *,
    category: str | None = None,
    intent: str | None = None,
) -> dict:
    areas = detect(text)
    lines: list[str] = []
    used: set[str] = set()
    for area in areas:
        rules = await rules_engine.rules_for(
            session, area=area, category=category, intent=intent
        )
        for rule in rules:
            key = f"{rule.area}:{rule.id}"
            if key in used:
                continue
            used.add(key)
            lines.append(f"[{rule.area}] {_rule_line(rule)}")
    return {
        "areas": areas,
        "rules": lines,
        "text": "\n".join(lines),
    }
