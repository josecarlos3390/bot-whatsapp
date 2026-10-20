"""Importa imágenes reales desde el catálogo público de ROHO.

Usa el sitemap archivado para encontrar la ficha del producto y extrae la
imagen cuyo nombre de archivo coincide con el SKU local. Solo acepta imágenes
públicas de roho.com.bo y valida que respondan 200.

Uso:
    python -m scripts.import_roho_images --limit 30 --dry-run
    python -m scripts.import_roho_images --limit 30
"""

from __future__ import annotations

import argparse
import asyncio
import html
import logging
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import CatalogItem, ProductImage

logger = logging.getLogger("import_roho_images")
SITEMAP = (
    "https://web.archive.org/web/20241204144934id_/"
    "https://roho.com.bo/wp-sitemap-posts-product-1.xml"
)
ARCHIVE = "https://web.archive.org/web/20250425213351/"
STOP = {
    "de", "del", "la", "el", "los", "las", "con", "para", "por", "en",
    "y", "o", "cm", "mm", "lt", "lts", "kg", "un", "und", "pza", "pzas",
}


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", html.unescape(value).lower())
        if len(token) > 2 and token not in STOP
    }


def load_slugs() -> list[tuple[str, str, set[str]]]:
    response = httpx.get(SITEMAP, timeout=30, follow_redirects=True)
    response.raise_for_status()
    urls = re.findall(r"<loc>(.*?)</loc>", response.text)
    rows = []
    for url in urls:
        match = re.search(r"/product/([^/]+)/?$", url)
        if match:
            slug = match.group(1)
            rows.append((slug, url, tokens(slug)))
    return rows


def best_slug(
    name: str,
    slugs: list[tuple[str, str, set[str]]],
    index: dict[str, list[int]],
) -> tuple[float, str]:
    wanted = tokens(name)
    if len(wanted) < 2:
        return 0.0, ""
    candidate_indices: set[int] = set()
    for token in wanted:
        candidate_indices.update(index.get(token, []))
    best_score = 0.0
    best = ""
    for i in list(candidate_indices)[:500]:
        slug, _url, slug_tokens = slugs[i]
        score = len(wanted & slug_tokens) / max(len(wanted | slug_tokens), 1)
        if score > best_score:
            best_score, best = score, slug
    return best_score, best


def extract_image(page: str) -> str | None:
    match = re.search(r'data-large_image="([^"]+)"', page)
    if not match:
        match = re.search(r'property="og:image" content="([^"]+)"', page)
    if not match:
        return None
    value = html.unescape(match.group(1))
    value = re.sub(
        r"^https://web\.archive\.org/web/[^/]+(?:im_)?/", "", value
    )
    return value


async def run(limit: int, per_category: int, *, dry_run: bool) -> None:
    await init_db()
    slugs = load_slugs()
    logger.info("Slugs ROHO: %s", len(slugs))
    async with SessionLocal() as session:
        items = list(
            (
                await session.scalars(
                    select(CatalogItem)
                    .where(
                        CatalogItem.active.is_(True),
                        CatalogItem.stock > 0,
                        CatalogItem.category.in_(
                            (
                                "LINEA BLANCA",
                                "MUEBLES",
                                "DECO HOGAR",
                                "PINTURA",
                                "BAÑOS",
                                "ILUMINACION",
                                "COCINAS",
                                "HERRAMIENTAS",
                            )
                        ),
                    )
                    .order_by(CatalogItem.stock.desc())
                )
            ).all()
        )
        candidates = []
        index: dict[str, list[int]] = defaultdict(list)
        for i, (_slug, _url, slug_tokens) in enumerate(slugs):
            for token in slug_tokens:
                index[token].append(i)
        for item in items:
            score, slug = best_slug(item.name, slugs, index)
            if score >= 0.55:
                candidates.append((score, item, slug))
        candidates.sort(key=lambda row: -row[0])
        logger.info("Candidatos: %s", len(candidates))

        loaded = 0
        per_category_count: dict[str, int] = {}
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True
        ) as client:
            for score, item, slug in candidates:
                if loaded >= limit:
                    break
                if per_category_count.get(item.category or "", 0) >= per_category:
                    continue
                page_url = ARCHIVE + f"https://roho.com.bo/product/{slug}/"
                try:
                    response = await client.get(page_url)
                    if response.status_code != 200:
                        continue
                    image_url = extract_image(response.text)
                except Exception:  # noqa: BLE001
                    logger.exception("No se pudo leer %s", slug)
                    continue
                if not image_url:
                    continue
                filename = Path(urlparse(image_url).path).stem.upper()
                if not (
                    filename == item.sku.upper()
                    or filename.startswith(item.sku.upper() + "-")
                ):
                    logger.info(
                        "SKU no coincide en imagen: %s vs %s", item.sku, filename
                    )
                    continue
                try:
                    head = await client.head(image_url)
                    if head.status_code != 200:
                        continue
                except Exception:  # noqa: BLE001
                    continue
                existing = await session.scalar(
                    select(ProductImage).where(
                        ProductImage.sku == item.sku,
                        ProductImage.url == image_url,
                    )
                )
                # La imagen real reemplaza al placeholder de demo.
                await session.execute(
                    ProductImage.__table__.delete().where(
                        ProductImage.sku == item.sku,
                        ProductImage.source == "demo",
                    )
                )
                if existing is None:
                    session.add(
                        ProductImage(
                            sku=item.sku,
                            url=image_url,
                            alt=item.name[:200],
                            position=1,
                            source="roho",
                            is_primary=True,
                            approved=True,
                        )
                    )
                else:
                    existing.is_primary = True
                    existing.approved = True
                    existing.source = "roho"
                item.image_url = image_url
                loaded += 1
                per_category_count[item.category or ""] = (
                    per_category_count.get(item.category or "", 0) + 1
                )
                logger.info(
                    "%s/%s %s -> %s",
                    loaded,
                    limit,
                    item.sku,
                    image_url,
                )
                if loaded % 5 == 0:
                    if dry_run:
                        await session.flush()
                    else:
                        await session.commit()
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    logger.info("Imágenes reales cargadas: %s", loaded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(
        run(
            max(args.limit, 1),
            max(args.per_category, 1),
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
