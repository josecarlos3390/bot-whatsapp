"""Motor de reglas de área: prioridad de marca y flujos."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaRule
from . import area_rules


def _fold(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    # Sin signos: "entrega?" y "entrega" deben ser la misma palabra.
    value = re.sub(r"[^a-z0-9ñü ]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


_SAME_GROUPS = (
    {"tv", "televisor", "television", "televisores", "pantalla"},
    {"heladera", "heladeras", "nevera", "refrigerador", "refri"},
    {"colchon", "colchones", "cama", "camas"},
    {"lavadora", "lavadoras", "lavarropas"},
    {"aire", "aires", "acondicionador", "acondicionadores"},
    # Logística: una regla de "envíos" también cubre "entrega" y "despacho".
    {
        "envios",
        "envio",
        "entrega",
        "entregas",
        "despacho",
        "despachos",
        "domicilio",
        "retiro",
        "retiros",
        "sucursal",
        "sucursales",
    },
    # Familia de herramientas: la regla puede decir "Herramientas" y aplicar
    # a las subcategorías reales del catálogo (taladros, sierras, etc.).
    {
        "herramientas",
        "herramienta",
        "herramientas manuales",
        "herramientas electricas",
        "herramientas de corte y desgaste",
        "taladros",
        "taladro",
        "rotomartillos",
        "rotomartillo",
        "sierras electricas",
        "sierras de mesa",
        "amoladoras y esmeriles",
        "amoladora",
        "atornilladores",
        "atornillador",
        "lijadoras",
        "lijadora",
        "cajas de herramientas",
        "set de herramientas",
    },
)


def same_category(left: str | None, right: str | None) -> bool:
    """¿Son la misma categoría o familia? (para el guard de coherencia)."""
    return _same(left, right)


def _same(left: str | None, right: str | None) -> bool:
    a, b = _fold(left), _fold(right)
    if not a or not b:
        return True
    if a == b:
        return True
    if a.rstrip("s") == b.rstrip("s"):
        return True
    if a.endswith("es") and a[:-2] == b:
        return True
    if b.endswith("es") and b[:-2] == a:
        return True
    for group in _SAME_GROUPS:
        if a in group and b in group:
            return True
    if len(a) > 3 and len(b) > 3 and (a in b or b in a):
        return True
    return False


def _matches(rule: AreaRule, *, category: str | None, intent: str | None) -> bool:
    condition = rule.condition or {}
    if condition.get("category"):
        if not category:
            return False
        if not _same(condition.get("category"), category):
            return False
    if condition.get("intent") and not _same(
        condition.get("intent"), intent
    ):
        return False
    return True


async def rules_for(
    session: AsyncSession,
    *,
    area: str | None = None,
    category: str | None = None,
    intent: str | None = None,
) -> list[AreaRule]:
    rows = await area_rules.active_rules(session, area=area)
    matched = [
        rule
        for rule in rows
        if _matches(rule, category=category, intent=intent)
    ]
    matched.sort(key=lambda rule: rule.priority, reverse=True)
    return matched


def order_brands(brands: list[str], rules: list[AreaRule]) -> list[str]:
    preferred: dict[str, int] = {}
    for rule in rules:
        if rule.rule_type != "brand_priority":
            continue
        brand = str((rule.action or {}).get("brand") or "").strip()
        if brand:
            preferred[_fold(brand)] = max(
                preferred.get(_fold(brand), 0), rule.priority
            )
    if not preferred:
        return brands
    original = {_fold(brand): index for index, brand in enumerate(brands)}
    return sorted(
        brands,
        key=lambda brand: (
            -preferred.get(_fold(brand), 0),
            original.get(_fold(brand), 999),
        ),
    )


def order_products(products: list[dict], rules: list[AreaRule]) -> list[dict]:
    preferred: dict[str, int] = {}
    for rule in rules:
        if rule.rule_type != "brand_priority":
            continue
        brand = str((rule.action or {}).get("brand") or "").strip()
        if brand:
            preferred[_fold(brand)] = max(
                preferred.get(_fold(brand), 0), rule.priority
            )
    if not preferred:
        return products
    return sorted(
        products,
        key=lambda product: (
            -preferred.get(
                _fold(str(product.get("brand") or "")), 0
            ),
            -int(product.get("stock") or 0),
        ),
    )


async def brand_rules(
    session: AsyncSession,
    *,
    category: str | None = None,
) -> list[AreaRule]:
    rows = await rules_for(
        session, area="ecommerce", category=category, intent=None
    )
    return [rule for rule in rows if rule.rule_type == "brand_priority"]


async def promotion_rules(
    session: AsyncSession,
    *,
    category: str | None = None,
    any_category: bool = False,
) -> list[AreaRule]:
    """Reglas de promoción activas.

    Con ``any_category`` se traen todas y cada producto se evalúa contra la
    categoría de la regla: así "Herramientas" funciona al buscar "taladro".
    """
    if any_category:
        rows = await area_rules.active_rules(session, area="ecommerce")
    else:
        rows = await rules_for(
            session, area="ecommerce", category=category, intent=None
        )
    return [rule for rule in rows if rule.rule_type == "promotion_priority"]


def _promotion_threshold(rule: AreaRule) -> Decimal:
    raw = (rule.action or {}).get("min_discount", 0)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        value = Decimal("0")
    return max(value, Decimal("0"))


def _applies_to_category(rule: AreaRule, category: str | None) -> bool:
    condition = rule.condition or {}
    wanted = condition.get("category")
    if not wanted:
        return True
    return _same(wanted, category)


def order_promotions(
    products: list[dict], rules: list[AreaRule]
) -> list[dict]:
    """Prioriza promociones que superan el mínimo de su categoría.

    Se evalúa contra la categoría de cada producto, no contra el texto de la
    búsqueda. No elimina productos: solo los ordena.
    """
    promos = [rule for rule in rules if rule.rule_type == "promotion_priority"]
    if not promos:
        return products

    def discount(product: dict) -> Decimal:
        try:
            return Decimal(
                str(product.get("promo_discount_percent") or "0")
            )
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def minimum_for(product: dict) -> Decimal | None:
        values = [
            _promotion_threshold(rule)
            for rule in promos
            if _applies_to_category(rule, product.get("category"))
        ]
        return min(values) if values else None

    def key(product: dict):
        value = discount(product)
        minimum = minimum_for(product)
        if minimum is None:
            return (1, -value)
        eligible = value >= minimum and int(product.get("stock") or 0) > 0
        return (0 if eligible else 1, -value)

    return sorted(products, key=key)


async def return_rule(
    session: AsyncSession,
) -> AreaRule | None:
    rows = await rules_for(
        session, area="calidad", category=None, intent="devolucion"
    )
    for rule in rows:
        if rule.rule_type == "return_flow" and (rule.action or {}).get("questions"):
            return rule
    return None
