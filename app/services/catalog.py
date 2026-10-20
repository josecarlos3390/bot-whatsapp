from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date
from decimal import Decimal

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogItem, ProductImage, ProductPromotion


SYNONYMS: dict[str, list[str]] = {    "living": ["sala", "sofa", "sillon", "mueble"],
    "sala": ["living", "sofa", "sillon", "mueble"],
    "sofa": ["sillon", "sala", "living"],
    "sillon": ["sofa", "sala", "living"],
    "refri": ["refrigerador", "heladera", "nevera", "linea blanca"],
    "refrigerador": ["refri", "heladera", "nevera", "linea blanca"],
    "heladera": ["refrigerador", "refri", "nevera"],
    "nevera": ["refrigerador", "refri", "heladera"],
    "tv": ["televisor", "television", "pantalla"],
    "tele": ["televisor", "television", "pantalla"],
    "televisor": ["tv", "television", "pantalla"],
    "television": ["tv", "televisor", "pantalla"],
    "colchon": ["cama", "dormitorio"],
    "cama": ["colchon", "dormitorio"],
    "lampara": ["iluminacion", "foco", "luz"],
    "foco": ["lampara", "iluminacion", "bombilla", "luz"],
    "bombilla": ["foco", "lampara", "iluminacion"],
    "ducha": ["bano", "griferia", "plomeria"],
    "bano": ["ducha", "griferia", "sanitario", "inodoro"],
    "griferia": ["grifo", "llave", "bano"],
    "grifo": ["griferia", "llave"],
    "aire": ["acondicionador", "split", "climatizacion"],
    "acondicionador": ["aire", "split", "climatizacion"],
    "split": ["aire", "acondicionador", "climatizacion"],
    "lavadora": ["lavarropas", "linea blanca"],
    "lavarropas": ["lavadora", "linea blanca"],
    "secadora": ["linea blanca"],
    "ventilador": ["aire", "climatizacion"],
    "pintura": ["latex", "esmalte", "barniz"],
    "jardin": ["exterior", "planta", "maceta"],
    "navidad": ["arbol", "navideno"],
    "cocina": ["mesada", "alacena", "mueble"],
    "blanco": ["blanca"],
    "blanca": ["blanco"],
    "negro": ["negra"],
    "negra": ["negro"],
    "rojo": ["roja"],
    "roja": ["rojo"],
    "amarillo": ["amarilla"],
    "amarilla": ["amarillo"],
    "gris": ["grises"],
    "grises": ["gris"],
}

INTENT_CATEGORY: dict[str, str] = {
    "living": "MUEBLES",
    "sala": "MUEBLES",
    "sofa": "MUEBLES",
    "sillon": "MUEBLES",
    "refri": "LINEA BLANCA",
    "refrigerador": "LINEA BLANCA",
    "heladera": "LINEA BLANCA",
    "nevera": "LINEA BLANCA",
    "tv": "LINEA BLANCA",
    "televisor": "LINEA BLANCA",
    "colchon": "DECO HOGAR",
    "colchones": "DECO HOGAR",
    "cama": "MUEBLES",
    "lampara": "ILUMINACION",
    "foco": "ILUMINACION",
    "ducha": "BAÑOS",
    "bano": "BAÑOS",
    "pintura": "PINTURA",
    "herramienta": "HERRAMIENTAS",
}
QUERY_STOPWORDS = {
    "busco", "buscar", "buscando", "necesito", "necesita", "quiero",
    "queria", "quisiera", "un", "una", "unos", "unas", "el", "la",
    "los", "las", "de", "del", "para", "por", "con", "sin", "en",
    "mi", "me", "algo", "algun", "alguna", "tienen", "tiene", "tienes",
    "hola", "buenas", "por favor", "favor",
}
TYPO_FIXES = {
    "plaas": "plazas",
    "plasa": "plazas",
    "colchom": "colchon",
    "refirgerador": "refrigerador",
    "lavadroa": "lavadora",
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).lower()


def _like(term: str) -> str:
    return f"%{term}%"


def _base_variants(term: str) -> list[str]:
    term = term.lower().strip()
    folded = _fold(term)
    bases = [term]
    if folded != term:
        bases.append(folded)
    variants = []
    for base in bases:
        base = base.strip()
        if not base:
            continue
        variants.append(base)
        if len(base) > 4 and base.endswith("es"):
            variants.append(base[:-2])
        elif len(base) > 3 and base.endswith("s"):
            variants.append(base[:-1])
    return list(dict.fromkeys(variants))


def _variants(term: str) -> list[str]:
    term = term.lower().strip()
    bases = _base_variants(term)
    for base in list(bases):
        for synonym in SYNONYMS.get(_fold(base), []):
            bases.extend(_base_variants(synonym))
    return list(dict.fromkeys(v for v in bases if v))


def _correct_terms(terms: list[str]) -> list[str]:
    vocabulary = sorted(
        set(SYNONYMS) | set(INTENT_CATEGORY) | set(TYPO_FIXES.values()) | {
            "refrigerador", "lavadora", "lavarropas", "colchon",
            "televisor", "lampara", "herramienta", "acondicionador",
            "plaza", "plazas",
        }
    )
    corrected = []
    for term in terms:
        folded = _fold(term)
        if folded in TYPO_FIXES:
            corrected.append(TYPO_FIXES[folded])
            continue
        if folded in vocabulary:
            corrected.append(term)
            continue
        match = difflib.get_close_matches(
            folded, vocabulary, n=1, cutoff=0.78
        )
        corrected.append(match[0] if match else term)
    return corrected


def _match_all(terms: list[str], *, expand: bool = True):
    clauses = []
    for term in terms:
        variants = _variants(term) if expand else _base_variants(term)
        patterns = [_like(variant) for variant in variants]
        clauses.append(
            or_(
                *[
                    column.ilike(pattern)
                    for pattern in patterns
                    for column in (
                        CatalogItem.name,
                        CatalogItem.description,
                        CatalogItem.keywords,
                        CatalogItem.sku,
                        CatalogItem.brand,
                    )
                ]
            )
        )
    return clauses


def _rank(item: CatalogItem, terms: list[str]) -> tuple[int, str]:
    name = _fold(item.name or "")
    category = _fold(item.category or "")
    brand = _fold(item.brand or "")
    best = 3
    for term in terms:
        for variant in _variants(term):
            variant = _fold(variant)
            if name.startswith(variant):
                best = min(best, 0)
            elif variant in name:
                best = min(best, 1)
            elif variant in category or variant in brand:
                best = min(best, 2)
    return best, name


async def categories(session: AsyncSession, limit: int = 10) -> list[dict]:
    rows = (
        await session.execute(
            select(CatalogItem.category, func.count(CatalogItem.sku))
            .where(
                CatalogItem.active.is_(True),
                CatalogItem.stock > 0,
                CatalogItem.category.is_not(None),
                CatalogItem.category != "",
            )
            .group_by(CatalogItem.category)
            .order_by(func.count(CatalogItem.sku).desc())
            .limit(max(int(limit), 1))
        )
    ).all()
    return [
        {"name": category, "count": int(count)}
        for category, count in rows
    ]


async def primary_image_info(
    session: AsyncSession, sku: str
) -> dict | None:
    image = await session.scalar(
        select(ProductImage)
        .where(
            ProductImage.sku == sku.strip().upper(),
            ProductImage.approved.is_(True),
        )
        .order_by(ProductImage.is_primary.desc(), ProductImage.position)
        .limit(1)
    )
    if image is not None:
        return {
            "url": image.url,
            "source": image.source,
            "alt": image.alt,
        }
    item = await get_item(session, sku)
    if item is not None and item.image_url:
        return {"url": item.image_url, "source": None, "alt": None}
    return None


async def primary_image(session: AsyncSession, sku: str) -> str | None:
    info = await primary_image_info(session, sku)
    return info["url"] if info else None


async def search_items(
    session: AsyncSession,
    query: str | None,
    limit: int = 5,
    only_available: bool = True,
    category: str | None = None,
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    only_discount: bool = False,
) -> list[CatalogItem]:
    """Búsqueda con filtros para armar un catálogo dinámico."""

    def base():
        stmt = select(CatalogItem).where(CatalogItem.active.is_(True))
        if only_available:
            stmt = stmt.where(
                CatalogItem.stock > 0, CatalogItem.price > 0
            )
        if category:
            patterns = [_like(v) for v in _variants(category)]
            starts = [f"{v}%" for v in _variants(category)]
            stmt = stmt.where(
                or_(
                    *[
                        CatalogItem.category.ilike(pattern)
                        for pattern in patterns
                    ],
                    *[
                        CatalogItem.name.ilike(pattern)
                        for pattern in starts
                    ],
                )
            )
        if brand:
            pattern = f"%{brand}%"
            stmt = stmt.where(
                or_(
                    CatalogItem.brand.ilike(pattern),
                    CatalogItem.name.ilike(pattern),
                )
            )
        if min_price is not None:
            stmt = stmt.where(
                CatalogItem.price >= Decimal(str(min_price))
            )
        if max_price is not None:
            stmt = stmt.where(
                CatalogItem.price <= Decimal(str(max_price))
            )
        if only_discount:
            today = date.today()
            promo = (
                select(ProductPromotion.id)
                .where(
                    ProductPromotion.sku == CatalogItem.sku,
                    ProductPromotion.tier_quantity.is_(None),
                    ProductPromotion.price < CatalogItem.price,
                    or_(
                        ProductPromotion.valid_from.is_(None),
                        ProductPromotion.valid_from <= today,
                    ),
                    or_(
                        ProductPromotion.valid_to.is_(None),
                        ProductPromotion.valid_to >= today,
                    ),
                )
                .exists()
            )
            stmt = stmt.where(promo)
        return stmt

    terms = [
        t
        for t in re.split(r"\s+", (query or "").strip())
        if t and _fold(t) not in QUERY_STOPWORDS
    ]
    size_match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*pla(?:z|a)[a-z]*\b",
        query or "",
        re.IGNORECASE,
    )
    size_phrase = (
        size_match.group(1).replace(",", ".") if size_match else None
    )
    intent_category = None
    if not category:
        for term in terms:
            intent_category = INTENT_CATEGORY.get(_fold(term))
            if intent_category:
                category = intent_category
                break
    rank_terms = terms + ([category] if category else [])
    fetch_limit = max(int(limit) * 5, int(limit))

    async def run(expanded: bool) -> list[CatalogItem]:
        stmt = base()
        if size_phrase:
            stmt = stmt.where(
                CatalogItem.name.ilike(f"%{size_phrase} plazas%")
            )
        if terms:
            stmt = stmt.where(
                *_match_all(terms[:4], expand=expanded)
            )
        return list(
            (
                await session.scalars(
                    stmt.order_by(CatalogItem.name).limit(fetch_limit)
                )
            ).all()
        )

    rows = await run(expanded=False)
    if terms and len(rows) < min(3, int(limit)):
        expanded = await run(expanded=True)
        seen = {item.sku for item in rows}
        rows.extend(item for item in expanded if item.sku not in seen)
    if not rows and terms:
        corrected = _correct_terms(terms)
        if corrected != terms:
            terms = corrected
            intent_category = None
            if not category:
                for term in terms:
                    intent_category = INTENT_CATEGORY.get(_fold(term))
                    if intent_category:
                        category = intent_category
                        break
            rank_terms = terms + ([category] if category else [])
            rows = await run(expanded=True)
    if not rows and terms:
        # Último intento: cualquier término, manteniendo los filtros.
        stmt = base().where(or_(*_match_all(terms[:4])))
        rows = list(
            (
                await session.scalars(
                    stmt.order_by(CatalogItem.name).limit(fetch_limit)
                )
            ).all()
        )
    rows.sort(key=lambda item: _rank(item, rank_terms))
    return rows[: int(limit)]


async def get_item(session: AsyncSession, sku: str) -> CatalogItem | None:
    return await session.scalar(
        select(CatalogItem).where(
            CatalogItem.sku == sku.strip(), CatalogItem.active.is_(True)
        )
    )


def price_of(item: CatalogItem) -> Decimal:
    return Decimal(item.price)
