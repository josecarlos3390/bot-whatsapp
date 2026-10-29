"""Política de reglas activas para una respuesta del bot."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaRule
from . import area_router, catalog, rules_engine

TRACE_PATH = Path("logs") / "bot_rules.jsonl"


@dataclass
class RulePolicy:
    areas: list[str] = field(default_factory=list)
    brand: str | None = None
    brand_area: str | None = None
    brand_priority: int = 0
    promotion_min: float | None = None
    promotion_area: str | None = None
    promotion_priority: int = 0
    instructions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)

    @property
    def has_product_rules(self) -> bool:
        return self.brand is not None or self.promotion_min is not None

    def prompt_text(self) -> str:
        if not self.rules:
            return (
                "No hay reglas de área activas para este mensaje. "
                "Respondé con datos reales."
            )
        lines = [
            "REGLAS OBLIGATORIAS DEL ÁREA (tienen prioridad sobre tu "
            "criterio comercial; no las inventes ni las contradigas):"
        ]
        if self.brand:
            lines.append(
                f"- Priorizar la marca {self.brand} en esta categoría."
            )
        if self.promotion_min is not None:
            lines.append(
                f"- Priorizar promociones con al menos "
                f"{self.promotion_min:g}% de descuento y stock."
            )
        for instruction in self.instructions:
            lines.append(f"- {instruction}")
        for question in self.questions:
            lines.append(f"- Preguntar antes de cerrar: {question}")
        lines.append(
            "Si una regla choca con stock o con un dato real, el dato real "
            "manda: no ofrezcas algo sin stock."
        )
        return "\n".join(lines)

    def violates_brand(
        self, answer: str, products: list[dict] | None = None
    ) -> bool:
        if not self.brand:
            return False
        text = (answer or "").lower()
        brand = self.brand.lower()
        if brand in text:
            return False
        other_brands = {
            str(product.get("brand") or "").lower()
            for product in products or []
            if product.get("brand")
            and str(product.get("brand")).lower() != brand
        }
        return any(
            other and other in text for other in other_brands if len(other) > 2
        )

    def audit(self) -> list[dict]:
        return [
            {
                "area": rule.get("area"),
                "name": rule.get("name"),
                "type": rule.get("rule_type"),
                "priority": rule.get("priority"),
            }
            for rule in self.rules
        ]


async def build(
    session: AsyncSession,
    text: str,
    *,
    category: str | None = None,
    intent: str | None = None,
) -> RulePolicy:
    policy = RulePolicy(areas=area_router.detect(text))
    category_hint = category or catalog.primary_term(text) or text
    seen: set[str] = set()
    # Si el mensaje no nombra un área, igual se buscan las reglas que dependen
    # solo de la categoría («Priorizar Samsung en heladeras»): antes, un atajo
    # como «las más elegidas» no aplicaba ninguna regla.
    # "general" es el área por defecto: se consulta sin filtro de área para
    # que apliquen las reglas que solo dependen de la categoría.
    areas = [area for area in policy.areas if area != "general"]
    for area in areas or [None]:
        rows = await rules_engine.rules_for(
            session, area=area, category=category_hint, intent=intent
        )
        for rule in rows:
            key = f"{rule.area}:{rule.id}"
            if key in seen:
                continue
            seen.add(key)
            policy.rules.append(
                {
                    "id": rule.id,
                    "area": rule.area,
                    "name": rule.name,
                    "rule_type": rule.rule_type,
                    "priority": rule.priority,
                }
            )
            action = rule.action or {}
            if rule.rule_type == "brand_priority":
                brand = str(action.get("brand") or "").strip()
                if brand and rule.priority > policy.brand_priority:
                    policy.brand = brand
                    policy.brand_area = rule.area
                    policy.brand_priority = rule.priority
            elif rule.rule_type == "promotion_priority":
                try:
                    minimum = float(action.get("min_discount", 0))
                except (TypeError, ValueError):
                    minimum = 0.0
                if (
                    policy.promotion_min is None
                    or rule.priority >= policy.promotion_priority
                ):
                    policy.promotion_min = minimum
                    policy.promotion_area = rule.area
                    policy.promotion_priority = rule.priority
            elif rule.rule_type == "response_rule":
                instruction = str(
                    action.get("instruction") or action.get("text") or ""
                ).strip()
                if instruction and instruction not in policy.instructions:
                    policy.instructions.append(instruction)
            elif rule.rule_type == "required_questions":
                for question in action.get("questions") or []:
                    value = (
                        question.get("text")
                        if isinstance(question, dict)
                        else question
                    )
                    if value and str(value) not in policy.questions:
                        policy.questions.append(str(value))
    return policy


def log_applied(policy: RulePolicy, *, contact_id: str, query: str) -> None:
    if not policy.rules:
        return
    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "query": query,
                        "contact_id": contact_id,
                        "areas": policy.areas,
                        "brand": policy.brand,
                        "promotion_min": policy.promotion_min,
                        "rules": policy.audit(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001 - la auditoría no debe romper el bot
        pass
