from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CatalogItem, ProductImage, ProductPromotion

logger = logging.getLogger(__name__)


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

    def base(apply_category: bool = True):
        stmt = select(CatalogItem).where(CatalogItem.active.is_(True))
        if only_available:
            stmt = stmt.where(
                CatalogItem.stock > 0, CatalogItem.price > 0
            )
        if category and apply_category:
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
    explicit_category = category is not None
    intent_category = None
    if not explicit_category:
        for term in terms:
            intent_category = INTENT_CATEGORY.get(_fold(term))
            if intent_category:
                break
    # La categoría deducida del término es una pista para ordenar, no un
    # filtro: forzarla descartaba coincidencias reales por nombre cuando el
    # grupo del artículo en SAP no coincide con INTENT_CATEGORY.
    rank_terms = terms + ([intent_category] if intent_category else [])
    fetch_limit = max(int(limit) * 10, 50)

    async def run(
        expanded: bool, apply_category: bool = True
    ) -> list[CatalogItem]:
        stmt = base(apply_category)
        if size_phrase:
            stmt = stmt.where(
                CatalogItem.name.ilike(f"%{size_phrase} plazas%")
            )
        if terms:
            stmt = stmt.where(
                *_match_all(terms[:4], expand=expanded)
            )
        # Priorizar en SQL los artículos cuyo nombre EMPIEZA con el término:
        # si se ordena sólo alfabéticamente, accesorios como "BOLSA PARA
        # LAVADORA" desplazan a la "LAVADORA" real fuera del límite.
        ordering = []
        for term in terms[:2]:
            for variant in _variants(term)[:2]:
                ordering.append(
                    case(
                        (CatalogItem.name.ilike(f"{variant}%"), 0),
                        else_=1,
                    )
                )
        ordering.append(CatalogItem.name)
        return list(
            (
                await session.scalars(
                    stmt.order_by(*ordering).limit(fetch_limit)
                )
            ).all()
        )

    rows = await run(expanded=False)
    if terms and len(rows) < min(3, int(limit)):
        expanded_rows = await run(expanded=True)
        seen = {item.sku for item in rows}
        rows.extend(
            item for item in expanded_rows if item.sku not in seen
        )
    if not rows and terms:
        corrected = _correct_terms(terms)
        if corrected != terms:
            terms = corrected
            intent_category = None
            if not explicit_category:
                for term in terms:
                    intent_category = INTENT_CATEGORY.get(_fold(term))
                    if intent_category:
                        break
            rank_terms = terms + (
                [intent_category] if intent_category else []
            )
            rows = await run(expanded=True)
    if not rows and intent_category:
        # Ningún nombre coincidió: mostramos la categoría deducida del término
        # en lugar de dejar al cliente sin opciones.
        category = intent_category
        rows = await run(expanded=False)
        category = None
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


async def upsert_sap_items(
    session: AsyncSession, items: list[dict]
) -> int:
    """Guarda en el catálogo local artículos traídos de SAP al vuelo.

    Devuelve cuántos artículos se agregaron (los existentes se actualizan).
    """
    clean: list[tuple[str, str, Decimal, int]] = []
    for item in items or []:
        sku = str(item.get("sku") or "").strip()
        name = str(item.get("name") or "").strip()
        if not sku or not name:
            continue
        try:
            price = Decimal(str(item.get("price") or 0))
        except (ArithmeticError, ValueError):
            price = Decimal("0")
        try:
            stock = int(item.get("stock") or 0)
        except (TypeError, ValueError):
            stock = 0
        clean.append((sku, name, price, stock))
    if not clean:
        return 0

    existing = {
        row.sku: row
        for row in (
            await session.scalars(
                select(CatalogItem).where(
                    CatalogItem.sku.in_([row[0] for row in clean])
                )
            )
        ).all()
    }
    synced_at = datetime.now(timezone.utc)
    added = 0
    for sku, name, price, stock in clean:
        row = existing.get(sku)
        if row is None:
            session.add(
                CatalogItem(
                    sku=sku,
                    name=name[:200],
                    description=name,
                    price=price,
                    currency="BOB",
                    stock=stock,
                    keywords=name,
                    active=True,
                    sap_valid=True,
                    synced_at=synced_at,
                )
            )
            added += 1
        else:
            row.name = name[:200]
            row.price = price
            row.stock = stock
            row.active = True
            row.sap_valid = True
            row.synced_at = synced_at
    await session.commit()
    if added:
        logger.info("Catálogo: %s artículos nuevos desde SAP", added)
    return added


def _relevance_terms(query: str) -> list[str]:
    return [
        t
        for t in re.split(r"\s+", _fold(query or ""))
        if len(t) >= 3 and t not in QUERY_STOPWORDS
    ]


def _is_relevant(item: CatalogItem, terms: list[str]) -> bool:
    haystack = _fold(
        f"{item.name or ''} {item.keywords or ''} {item.brand or ''} "
        f"{item.category or ''}"
    )
    return any(term in haystack for term in terms)


async def quantity_tiers(
    session: AsyncSession, sku: str
) -> list[tuple[int, Decimal]]:
    """Escalones de precio por cantidad vigentes para un SKU."""
    today = date.today()
    rows = (
        await session.scalars(
            select(ProductPromotion)
            .where(
                ProductPromotion.sku == sku.strip().upper(),
                ProductPromotion.price_list == settings.sap_price_list,
                ProductPromotion.tier_quantity.is_not(None),
                or_(
                    ProductPromotion.valid_from.is_(None),
                    ProductPromotion.valid_from <= today,
                ),
                or_(
                    ProductPromotion.valid_to.is_(None),
                    ProductPromotion.valid_to >= today,
                ),
            )
            .order_by(ProductPromotion.tier_quantity)
        )
    ).all()
    return [
        (int(row.tier_quantity), Decimal(row.price))
        for row in rows
        if row.tier_quantity and row.price
    ]


# Qué ofrecer junto a un producto (siempre con stock).
COMPLEMENT_TERMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("COLCHON",), ("ALMOHADA", "PROTECTOR COLCHON")),
    (("LAVADORA", "SECADORA"), ("DETERGENTE",)),
    (("TALADRO", "ATORNILLADOR"), ("BROCA",)),
    (("PINTURA", "ESMALTE"), ("RODILLO", "BROCHA")),
)


async def complements(
    session: AsyncSession, sku: str, name: str, limit: int = 1
) -> list[CatalogItem]:
    """Productos que suelen comprarse junto al artículo, con stock."""
    upper = (name or "").upper()
    terms = next(
        (
            options
            for keys, options in COMPLEMENT_TERMS
            if any(key in upper for key in keys)
        ),
        (),
    )
    found: list[CatalogItem] = []
    seen: set[str] = {sku.strip().upper()}
    for term in terms:
        rows = await search_items(session, term, limit=limit + 3)
        for row in rows:
            if row.sku in seen or row.stock <= 0:
                continue
            found.append(row)
            seen.add(row.sku)
            break
        if len(found) >= limit:
            break
    return found[:limit]


def primary_term(query: str | None) -> str | None:
    """Palabra más significativa de la consulta (ignora "buscar", "quiero"...)."""
    terms = _relevance_terms(query or "")
    if not terms:
        return None
    return max(terms, key=len)


def is_head_match(item: CatalogItem, query: str | None) -> bool:
    """¿El nombre del artículo empieza con el término principal de la consulta?

    Sirve para distinguir "LAVADORA 10KG…" de "BOLSA PARA LAVADORA": cuando
    ninguna coincide así, el bot ofrece alternativas en lugar de presentar
    accesorios como si fueran el producto pedido.
    """
    terms = _relevance_terms(query or "")
    if not terms:
        return True
    name = _fold(item.name or "")
    return any(name.startswith(term) for term in terms)


def _sap_candidates(query: str, terms: list[str]) -> list[str]:
    """Frases y palabras para probar en SAP.

    SAP busca texto contiguo (`contains`), así que además de la frase se
    prueban las palabras más largas y sus variantes de plural.
    """
    words = [
        w
        for w in (query or "").split()
        if _fold(w) not in QUERY_STOPWORDS
    ]
    candidates: list[str] = []
    phrase = " ".join(words).strip()
    if phrase:
        candidates.append(phrase)
    for token in sorted(set(terms), key=len, reverse=True)[:3]:
        if token not in candidates:
            candidates.append(token)
        for variant in _variants(token)[1:3]:
            if variant not in candidates:
                candidates.append(variant)
    return candidates[:5]


async def search_with_sap(
    session: AsyncSession,
    query: str | None,
    *,
    sap,
    limit: int = 5,
) -> list[CatalogItem]:
    """Busca en el catálogo local y, si no hay coincidencias reales, en SAP.

    Lo que SAP devuelve se guarda en la base para que la próxima consulta se
    resuelva localmente.
    """
    rows = await search_items(session, query, limit=limit)
    terms = _relevance_terms(query or "")
    if not terms or sap is None:
        return rows
    if any(_is_relevant(row, terms) for row in rows):
        return rows

    found: dict[str, dict] = {}
    for candidate in _sap_candidates(query or "", terms)[:3]:
        try:
            items = await sap.search_items(candidate, limit=max(limit, 8))
        except Exception:  # noqa: BLE001 - una búsqueda en caliente nunca rompe el chat
            logger.exception("Búsqueda en caliente falló para %s", candidate)
            break
        for item in items or []:
            sku = str(item.get("sku") or "").strip()
            if sku:
                found.setdefault(sku, item)
        if len(found) >= limit:
            break

    if not found:
        return rows
    await upsert_sap_items(session, list(found.values()))
    return await search_items(session, query, limit=limit)


def price_of(item: CatalogItem) -> Decimal:
    return Decimal(item.price)
