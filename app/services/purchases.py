"""Historial de compras SAP y recomendaciones basadas en el cliente."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogItem,
    Contact,
    ProductPromotion,
    PurchaseHistory,
    PurchaseHistoryLine,
)
from ..sap import ServiceLayerSap

logger = logging.getLogger(__name__)
PAGE_SIZE = 20


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def sync_contact_purchases(
    session: AsyncSession,
    contact: Contact,
    sap: ServiceLayerSap,
    *,
    max_docs: int = 100,
) -> int:
    """Trae facturas del cliente desde SAP y reemplaza su historial local."""
    card_code = (contact.sap_card_code or "").strip()
    if not card_code:
        return 0

    docs: list[dict] = []
    skip = 0
    escaped_code = card_code.replace("'", "''")
    while len(docs) < max_docs:
        data = await sap.get(
            "Invoices",
            params={
                "$filter": f"CardCode eq '{escaped_code}'",
                "$top": PAGE_SIZE,
                "$skip": skip,
                "$orderby": "DocDate desc",
                "$select": (
                    "DocEntry,DocNum,DocDate,DocTotal,DocCurrency,"
                    "CardCode,CardName,DocumentLines"
                ),
            },
        )
        batch = data.get("value", [])
        if not batch:
            break
        docs.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        skip += PAGE_SIZE

    old_ids = select(PurchaseHistory.id).where(
        PurchaseHistory.contact_id == contact.id,
        PurchaseHistory.doc_type == "invoice",
    )
    await session.execute(
        delete(PurchaseHistoryLine).where(
            PurchaseHistoryLine.history_id.in_(old_ids)
        )
    )
    await session.execute(
        delete(PurchaseHistory).where(
            PurchaseHistory.contact_id == contact.id,
            PurchaseHistory.doc_type == "invoice",
        )
    )

    skus = {
        line.get("ItemCode")
        for doc in docs
        for line in (doc.get("DocumentLines") or [])
        if line.get("ItemCode")
    }
    categories: dict[str, str | None] = {}
    if skus:
        rows = await session.execute(
            select(CatalogItem.sku, CatalogItem.category).where(
                CatalogItem.sku.in_(skus)
            )
        )
        categories = {sku: category for sku, category in rows.all()}

    inserted = 0
    for doc in docs:
        doc_date = _as_date(doc.get("DocDate"))
        if doc_date is None:
            continue
        history = PurchaseHistory(
            contact_id=contact.id,
            sap_doc_entry=int(doc["DocEntry"]),
            doc_type="invoice",
            doc_num=doc.get("DocNum"),
            doc_date=doc_date,
            total=Decimal(str(doc.get("DocTotal") or 0)),
            currency=doc.get("DocCurrency") or "BOB",
        )
        session.add(history)
        await session.flush()
        for line in doc.get("DocumentLines") or []:
            sku = line.get("ItemCode")
            if not sku:
                continue
            session.add(
                PurchaseHistoryLine(
                    history_id=history.id,
                    sku=sku,
                    name=line.get("ItemDescription"),
                    category=categories.get(sku),
                    quantity=Decimal(str(line.get("Quantity") or 0)),
                    amount=Decimal(str(line.get("LineTotal") or 0)),
                )
            )
        inserted += 1

    await session.commit()
    logger.info("Compras de %s: %s facturas", card_code, inserted)
    return inserted


async def sync_invoice_by_doc_entry(
    session: AsyncSession, sap: ServiceLayerSap, doc_entry: int
) -> dict:
    """Upsert one invoice for an already-linked contact."""
    data = await sap.get(
        f"Invoices({int(doc_entry)})",
        params={
            "$select": (
                "DocEntry,DocNum,DocDate,DocTotal,DocCurrency,"
                "CardCode,CardName,DocumentLines"
            )
        },
    )
    card_code = (data.get("CardCode") or "").strip()
    contact = await session.scalar(
        select(Contact).where(Contact.sap_card_code == card_code)
    )
    if contact is None:
        return {
            "ok": False,
            "reason": "contact_not_linked",
            "card_code": card_code,
        }

    doc_date = _as_date(data.get("DocDate"))
    if doc_date is None:
        return {"ok": False, "reason": "invalid_doc_date"}

    old_ids = select(PurchaseHistory.id).where(
        PurchaseHistory.contact_id == contact.id,
        PurchaseHistory.doc_type == "invoice",
        PurchaseHistory.sap_doc_entry == int(doc_entry),
    )
    await session.execute(
        delete(PurchaseHistoryLine).where(
            PurchaseHistoryLine.history_id.in_(old_ids)
        )
    )
    await session.execute(
        delete(PurchaseHistory).where(
            PurchaseHistory.contact_id == contact.id,
            PurchaseHistory.doc_type == "invoice",
            PurchaseHistory.sap_doc_entry == int(doc_entry),
        )
    )

    lines = data.get("DocumentLines") or []
    skus = {line.get("ItemCode") for line in lines if line.get("ItemCode")}
    categories: dict[str, str | None] = {}
    if skus:
        rows = await session.execute(
            select(CatalogItem.sku, CatalogItem.category).where(
                CatalogItem.sku.in_(skus)
            )
        )
        categories = {sku: category for sku, category in rows.all()}

    history = PurchaseHistory(
        contact_id=contact.id,
        sap_doc_entry=int(doc_entry),
        doc_type="invoice",
        doc_num=data.get("DocNum"),
        doc_date=doc_date,
        total=Decimal(str(data.get("DocTotal") or 0)),
        currency=data.get("DocCurrency") or "BOB",
    )
    session.add(history)
    await session.flush()
    for line in lines:
        sku = line.get("ItemCode")
        if not sku:
            continue
        session.add(
            PurchaseHistoryLine(
                history_id=history.id,
                sku=sku,
                name=line.get("ItemDescription"),
                category=categories.get(sku),
                quantity=Decimal(str(line.get("Quantity") or 0)),
                amount=Decimal(str(line.get("LineTotal") or 0)),
            )
        )
    await session.commit()
    logger.info("Factura %s sincronizada para %s", doc_entry, card_code)
    return {
        "ok": True,
        "card_code": card_code,
        "contact_id": contact.id,
        "doc_entry": int(doc_entry),
    }


async def history_summary(session: AsyncSession, contact_id: str) -> dict:
    total_row = await session.execute(
        select(
            func.count(PurchaseHistory.id),
            func.coalesce(func.sum(PurchaseHistory.total), 0),
            func.max(PurchaseHistory.doc_date),
        ).where(PurchaseHistory.contact_id == contact_id)
    )
    count, total, last_date = total_row.one()
    category_rows = await session.execute(
        select(
            PurchaseHistoryLine.category,
            func.sum(PurchaseHistoryLine.amount),
        )
        .join(
            PurchaseHistory,
            PurchaseHistory.id == PurchaseHistoryLine.history_id,
        )
        .where(
            PurchaseHistory.contact_id == contact_id,
            PurchaseHistoryLine.category.is_not(None),
        )
        .group_by(PurchaseHistoryLine.category)
        .order_by(func.sum(PurchaseHistoryLine.amount).desc())
        .limit(5)
    )
    return {
        "count": int(count or 0),
        "total": str(Decimal(str(total or 0))),
        "last_purchase": last_date.isoformat() if last_date else None,
        "top_categories": [
            {"category": category, "amount": str(Decimal(str(amount or 0)))}
            for category, amount in category_rows.all()
            if category
        ],
    }


async def history_text(session: AsyncSession, contact_id: str) -> str:
    summary = await history_summary(session, contact_id)
    if not summary["count"]:
        return ""
    categories = ", ".join(
        row["category"] for row in summary["top_categories"][:3]
    )
    return (
        f"Compras: {summary['count']} · total Bs {summary['total']} · "
        f"última {summary['last_purchase']}"
        + (f" · categorías: {categories}" if categories else "")
    )


async def get_history(
    session: AsyncSession, contact_id: str, limit: int = 10
) -> dict:
    summary = await history_summary(session, contact_id)
    rows = (
        await session.scalars(
            select(PurchaseHistory)
            .where(PurchaseHistory.contact_id == contact_id)
            .order_by(PurchaseHistory.doc_date.desc())
            .limit(max(int(limit), 1))
        )
    ).all()
    purchases = []
    for row in rows:
        lines = (
            await session.scalars(
                select(PurchaseHistoryLine)
                .where(PurchaseHistoryLine.history_id == row.id)
                .limit(20)
            )
        ).all()
        purchases.append(
            {
                "doc_num": row.doc_num,
                "date": row.doc_date.isoformat(),
                "total": str(row.total),
                "currency": row.currency,
                "lines": [
                    {
                        "sku": line.sku,
                        "name": line.name,
                        "category": line.category,
                        "quantity": str(line.quantity),
                        "amount": str(line.amount),
                    }
                    for line in lines
                ],
            }
        )
    return {"ok": True, "summary": summary, "purchases": purchases}


async def recommend_for_customer(
    session: AsyncSession,
    contact_id: str,
    *,
    need: str | None = None,
    limit: int = 3,
    min_price: float = 20,
) -> dict:
    summary = await history_summary(session, contact_id)
    categories = [
        row["category"] for row in summary["top_categories"]
    ]
    today = date.today()

    stmt = (
        select(ProductPromotion, CatalogItem)
        .join(CatalogItem, CatalogItem.sku == ProductPromotion.sku)
        .where(
            CatalogItem.active.is_(True),
            CatalogItem.stock > 0,
            CatalogItem.price >= Decimal(str(min_price or 0)),
            ProductPromotion.tier_quantity.is_(None),
            ProductPromotion.price > 0,
            or_(
                ProductPromotion.valid_from.is_(None),
                ProductPromotion.valid_from <= today,
            ),
            or_(
                ProductPromotion.valid_to.is_(None),
                ProductPromotion.valid_to >= today,
            ),
        )
    )
    if categories:
        stmt = stmt.where(CatalogItem.category.in_(categories))
    if need:
        stmt = stmt.where(
            or_(
                CatalogItem.name.ilike(f"%{need}%"),
                CatalogItem.category.ilike(f"%{need}%"),
            )
        )
    stmt = stmt.limit(120)
    rows = (await session.execute(stmt)).all()

    candidates = []
    seen: set[str] = set()
    for promo, item in rows:
        if promo.sku in seen or item.price <= 0:
            continue
        seen.add(promo.sku)
        discount = (
            (Decimal(item.price) - Decimal(promo.price))
            / Decimal(item.price)
            * 100
        ).quantize(Decimal("0.01"))
        if discount <= 0:
            continue
        candidates.append(
            {
                "sku": promo.sku,
                "name": item.name,
                "category": item.category,
                "base_price": str(item.price),
                "final_price": str(promo.price),
                "discount_percent": str(discount),
                "valid_to": promo.valid_to.isoformat()
                if promo.valid_to
                else None,
                "reason": (
                    f"Ya compraste en {item.category}"
                    if item.category in categories
                    else "Promoción vigente"
                ),
            }
        )
    candidates.sort(
        key=lambda row: Decimal(row["discount_percent"]), reverse=True
    )
    return {
        "ok": True,
        "summary": summary,
        "recommendations": candidates[: max(int(limit), 1)],
        "cold_start": not summary["count"],
    }
