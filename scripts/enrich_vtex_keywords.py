"""Enriquece artículos activos con KeyWords y especificaciones de VTEX.

La búsqueda masiva de VTEX no devuelve `KeyWords`; el detalle del SKU sí.
Este script recorre los artículos activos del bot, consulta el detalle a
través de PaasVTEX y actualiza la base local por lotes.

Uso:
    python -m scripts.enrich_vtex_keywords --limit 20 --dry-run
    python -m scripts.enrich_vtex_keywords --all --concurrency 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import CatalogItem

logger = logging.getLogger("enrich_vtex_keywords")

SPEC_KEYS = {
    "product_type": ("Tipo", "Type"),
    "color": ("Color",),
    "material": ("Material",),
}


def _needs_refresh(item: CatalogItem, refresh_days: int) -> bool:
    attributes = item.attributes if isinstance(item.attributes, dict) else {}
    source = item.keywords_source or attributes.get("keywords_source")
    if source != "vtex":
        return True
    if refresh_days <= 0:
        return True
    raw = item.keywords_synced_at or attributes.get("keywords_synced_at")
    if not raw:
        return True
    try:
        synced = (
            raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
        )
        if synced.tzinfo is None:
            synced = synced.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - synced >= timedelta(days=refresh_days)


def _joined_keywords(item: CatalogItem, detail: dict) -> str | None:
    parts = [
        detail.get("keywords"),
        item.name,
        item.brand,
        item.category,
        item.barcode,
    ]
    specs = detail.get("specifications")
    if isinstance(specs, dict):
        parts.extend(f"{key} {value}" for key, value in specs.items())
    text = " ".join(str(part) for part in parts if part)
    return text[:4000] or None


def _apply_detail(item: CatalogItem, detail: dict) -> bool:
    attributes = dict(item.attributes or {})
    changed = False
    specs = detail.get("specifications")
    if isinstance(specs, dict) and specs:
        attributes["specs"] = {
            str(key)[:40]: str(value)[:120]
            for key, value in specs.items()
            if str(key).strip() and str(value).strip()
        }
        changed = True
    for field, names in SPEC_KEYS.items():
        value = detail.get(field)
        if not value and isinstance(specs, dict):
            for name in names:
                value = specs.get(name)
                if value:
                    break
        if value:
            attributes[field] = str(value)[:120]
            changed = True
    if detail.get("keywords"):
        keywords = _joined_keywords(item, detail)
        if keywords and keywords != item.keywords:
            item.keywords = keywords
            changed = True
    ahora = datetime.now(timezone.utc)
    attributes["keywords_source"] = "vtex"
    attributes["keywords_synced_at"] = ahora.isoformat()
    # Columnas propias (el JSON queda como respaldo para las especificaciones).
    item.product_type = (
        str(detail.get("product_type"))[:80]
        if detail.get("product_type")
        else item.product_type
        or (
            str(attributes.get("product_type"))[:80]
            if attributes.get("product_type")
            else None
        )
    )
    item.color = (
        str(detail.get("color"))[:60]
        if detail.get("color")
        else item.color or (
            str(attributes.get("color"))[:60] if attributes.get("color") else None
        )
    )
    item.material = (
        str(detail.get("material"))[:60]
        if detail.get("material")
        else item.material
        or (
            str(attributes.get("material"))[:60]
            if attributes.get("material")
            else None
        )
    )
    item.keywords_source = "vtex"
    item.keywords_synced_at = ahora
    changed = True
    if changed:
        item.attributes = attributes
    return changed


async def _fetch(
    client: httpx.AsyncClient,
    sku: str,
    semaphore: asyncio.Semaphore,
    delay: float,
) -> dict | None:
    async with semaphore:
        await asyncio.sleep(max(delay, 0))
        url = f"/api/vtex/items/{sku}"
        for attempt in range(6):
            try:
                response = await asyncio.wait_for(
                    client.get(url, timeout=30), timeout=45
                )
                if response.status_code == 404:
                    return None
                if response.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(5.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
            except (asyncio.TimeoutError, httpx.HTTPError, ValueError):
                if attempt == 5:
                    logger.warning("No se pudo enriquecer %s", sku)
                    return None
                await asyncio.sleep(3.0 * (attempt + 1))
    return None


async def run(
    *,
    limit: int | None,
    all_items: bool,
    concurrency: int,
    delay: float,
    refresh_days: int,
    dry_run: bool,
) -> dict:
    await init_db()
    async with SessionLocal() as session:
        stmt = (
            select(CatalogItem)
            .where(CatalogItem.active.is_(True))
            .order_by(CatalogItem.sku)
        )
        if limit and not all_items:
            stmt = stmt.limit(limit)
        items = list((await session.scalars(stmt)).all())

    pending = [
        item
        for item in items
        if _needs_refresh(item, refresh_days)
    ]
    logger.info(
        "Artículos activos: %s · pendientes de keywords: %s",
        len(items),
        len(pending),
    )
    if dry_run:
        return {
            "active": len(items),
            "pending": len(pending),
            "updated": 0,
            "failed": 0,
        }

    base = (settings.sap_paas_url or "").rstrip("/")
    if not base:
        raise RuntimeError("SAP_PAAS_URL no está configurado")
    semaphore = asyncio.Semaphore(max(1, concurrency))
    updated = 0
    failed = 0
    headers = {"X-Api-Key": settings.sap_paas_api_key}
    async with httpx.AsyncClient(base_url=base + "/", headers=headers) as client:
        for start in range(0, len(pending), 50):
            batch = pending[start : start + 50]
            details = await asyncio.gather(
                *[
                    _fetch(client, item.sku, semaphore, delay)
                    for item in batch
                ]
            )
            async with SessionLocal() as session:
                for item, detail in zip(batch, details):
                    if not detail:
                        failed += 1
                        continue
                    row = await session.get(CatalogItem, item.id)
                    if row is None:
                        continue
                    if _apply_detail(row, detail):
                        updated += 1
                await session.commit()
            logger.info(
                "Progreso keywords: %s/%s (actualizados %s, fallidos %s)",
                min(start + 50, len(pending)),
                len(pending),
                updated,
                failed,
            )
    return {
        "active": len(items),
        "pending": len(pending),
        "updated": updated,
        "failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enriquece keywords y especificaciones desde VTEX"
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--refresh-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    result = asyncio.run(
        run(
            limit=args.limit,
            all_items=args.all,
            concurrency=min(max(args.concurrency, 1), 12),
            delay=max(args.delay, 0),
            refresh_days=max(args.refresh_days, 0),
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
