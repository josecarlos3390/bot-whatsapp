"""Reglas de negocio por área (ecommerce, calidad, marketing, etc.)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaRule, AreaRuleVersion

AREAS = {"ecommerce", "calidad", "marketing", "operaciones", "general"}
RULE_TYPES = {
    "brand_priority",
    "promotion_priority",
    "return_flow",
    "response_rule",
    "required_questions",
}
STATUSES = {"draft", "published", "archived"}


class RuleError(ValueError):
    pass


def _validate(
    *,
    area: str,
    name: str,
    rule_type: str,
    condition: dict,
    action: dict,
    status: str,
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    if area not in AREAS:
        raise RuleError(f"Área inválida: {area}")
    if not (name or "").strip():
        raise RuleError("La regla necesita un nombre")
    if rule_type not in RULE_TYPES:
        raise RuleError(f"Tipo de regla inválido: {rule_type}")
    if status not in STATUSES:
        raise RuleError(f"Estado inválido: {status}")
    if not isinstance(condition, dict) or not isinstance(action, dict):
        raise RuleError("condition y action deben ser objetos JSON")
    if valid_from and valid_to and valid_to < valid_from:
        raise RuleError("valid_to no puede ser anterior a valid_from")
    if rule_type == "brand_priority" and not action.get("brand"):
        raise RuleError("brand_priority necesita action.brand")
    if rule_type == "promotion_priority":
        if not condition.get("category"):
            raise RuleError(
                "promotion_priority necesita condition.category"
            )
        if "min_discount" not in action:
            raise RuleError("promotion_priority necesita min_discount")
        try:
            minimum = float(action.get("min_discount", 0))
        except (TypeError, ValueError) as exc:
            raise RuleError(
                "promotion_priority necesita min_discount numérico"
            ) from exc
        if minimum < 0 or minimum > 100:
            raise RuleError("min_discount debe estar entre 0 y 100")
    if rule_type == "return_flow" and not action.get("questions"):
        raise RuleError("return_flow necesita action.questions")


def to_dict(rule: AreaRule) -> dict:
    return {
        "id": rule.id,
        "area": rule.area,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "condition": rule.condition or {},
        "action": rule.action or {},
        "priority": rule.priority,
        "status": rule.status,
        "valid_from": rule.valid_from.isoformat() if rule.valid_from else None,
        "valid_to": rule.valid_to.isoformat() if rule.valid_to else None,
        "version": rule.version,
        "created_by": rule.created_by,
        "updated_by": rule.updated_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


async def list_rules(
    session: AsyncSession,
    *,
    area: str | None = None,
    status: str | None = None,
    rule_type: str | None = None,
) -> list[AreaRule]:
    stmt = select(AreaRule).order_by(
        AreaRule.priority.desc(), AreaRule.updated_at.desc()
    )
    if area:
        stmt = stmt.where(AreaRule.area == area)
    if status:
        stmt = stmt.where(AreaRule.status == status)
    if rule_type:
        stmt = stmt.where(AreaRule.rule_type == rule_type)
    return list((await session.scalars(stmt)).all())


async def get_rule(session: AsyncSession, rule_id: str) -> AreaRule | None:
    return await session.get(AreaRule, rule_id)


async def _snapshot(
    session: AsyncSession, rule: AreaRule, changed_by: str
) -> None:
    session.add(
        AreaRuleVersion(
            rule_id=rule.id,
            version=rule.version,
            snapshot=to_dict(rule),
            changed_by=changed_by,
        )
    )


async def create_rule(
    session: AsyncSession,
    *,
    area: str,
    name: str,
    rule_type: str,
    condition: dict | None = None,
    action: dict | None = None,
    priority: int = 0,
    status: str = "draft",
    valid_from: date | None = None,
    valid_to: date | None = None,
    changed_by: str = "admin",
) -> AreaRule:
    condition = condition or {}
    action = action or {}
    _validate(
        area=area,
        name=name,
        rule_type=rule_type,
        condition=condition,
        action=action,
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    rule = AreaRule(
        area=area,
        name=name.strip(),
        rule_type=rule_type,
        condition=condition,
        action=action,
        priority=int(priority or 0),
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        version=1,
        created_by=changed_by,
        updated_by=changed_by,
    )
    session.add(rule)
    await session.flush()
    await _snapshot(session, rule, changed_by)
    await session.commit()
    return rule


async def update_rule(
    session: AsyncSession,
    rule: AreaRule,
    *,
    name: str | None = None,
    rule_type: str | None = None,
    condition: dict | None = None,
    action: dict | None = None,
    priority: int | None = None,
    status: str | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    changed_by: str = "admin",
) -> AreaRule:
    next_name = name if name is not None else rule.name
    next_type = rule_type if rule_type is not None else rule.rule_type
    next_condition = condition if condition is not None else rule.condition
    next_action = action if action is not None else rule.action
    next_status = status if status is not None else rule.status
    next_from = valid_from if valid_from is not None else rule.valid_from
    next_to = valid_to if valid_to is not None else rule.valid_to
    _validate(
        area=rule.area,
        name=next_name,
        rule_type=next_type,
        condition=next_condition or {},
        action=next_action or {},
        status=next_status,
        valid_from=next_from,
        valid_to=next_to,
    )
    rule.name = next_name.strip()
    rule.rule_type = next_type
    rule.condition = next_condition or {}
    rule.action = next_action or {}
    rule.priority = int(priority if priority is not None else rule.priority)
    rule.status = next_status
    rule.valid_from = next_from
    rule.valid_to = next_to
    rule.version += 1
    rule.updated_by = changed_by
    await session.flush()
    await _snapshot(session, rule, changed_by)
    await session.commit()
    return rule


async def set_status(
    session: AsyncSession,
    rule: AreaRule,
    status: str,
    *,
    changed_by: str = "admin",
) -> AreaRule:
    if status not in STATUSES:
        raise RuleError(f"Estado inválido: {status}")
    rule.status = status
    rule.version += 1
    rule.updated_by = changed_by
    await session.flush()
    await _snapshot(session, rule, changed_by)
    await session.commit()
    return rule


async def delete_rule(session: AsyncSession, rule: AreaRule) -> None:
    await session.delete(rule)
    await session.commit()


async def active_rules(
    session: AsyncSession,
    *,
    area: str | None = None,
    today: date | None = None,
) -> list[AreaRule]:
    today = today or date.today()
    rows = await list_rules(session, area=area, status="published")
    return [
        rule
        for rule in rows
        if (rule.valid_from is None or rule.valid_from <= today)
        and (rule.valid_to is None or today <= rule.valid_to)
    ]


async def list_versions(
    session: AsyncSession, rule_id: str
) -> list[AreaRuleVersion]:
    return list(
        (
            await session.scalars(
                select(AreaRuleVersion)
                .where(AreaRuleVersion.rule_id == rule_id)
                .order_by(AreaRuleVersion.version.desc())
            )
        ).all()
    )


def _as_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


async def rollback_rule(
    session: AsyncSession,
    rule: AreaRule,
    version: int,
    *,
    changed_by: str = "admin",
) -> AreaRule:
    snapshot_row = await session.scalar(
        select(AreaRuleVersion).where(
            AreaRuleVersion.rule_id == rule.id,
            AreaRuleVersion.version == version,
        )
    )
    if snapshot_row is None:
        raise RuleError(f"No existe la versión {version}")
    snapshot = snapshot_row.snapshot or {}
    try:
        return await update_rule(
            session,
            rule,
            name=snapshot.get("name"),
            rule_type=snapshot.get("rule_type"),
            condition=snapshot.get("condition") or {},
            action=snapshot.get("action") or {},
            priority=int(snapshot.get("priority") or 0),
            status=snapshot.get("status") or "draft",
            valid_from=_as_date(snapshot.get("valid_from")),
            valid_to=_as_date(snapshot.get("valid_to")),
            changed_by=changed_by,
        )
    except (TypeError, ValueError) as exc:
        raise RuleError(f"No se pudo restaurar la versión: {exc}") from exc
