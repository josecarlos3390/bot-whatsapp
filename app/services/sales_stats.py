"""Sales statistics from SAP invoices for best sellers."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogItem, ProductSalesStat


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def aggregate_invoice_docs(docs: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    cutoff_30 = today - timedelta(days=30)
    cutoff_90 = today - timedelta(days=90)
    stats: dict[str, dict] = {}
    for doc in docs:
        doc_date = _as_date(doc.get("DocDate"))
        if doc_date is None or doc_date < cutoff_90:
            continue
        for line in doc.get("DocumentLines") or []:
            sku = (line.get("ItemCode") or "").strip()
            if not sku:
                continue
            try:
                quantity = int(float(line.get("Quantity") or 0))
            except (TypeError, ValueError):
                quantity = 0
            if quantity <= 0:
                continue
            amount = Decimal(str(line.get("LineTotal") or 0))
            row = stats.setdefault(
                sku,
                {
                    "units_30d": 0,
                    "revenue_30d": Decimal("0"),
                    "units_90d": 0,
                    "revenue_90d": Decimal("0"),
                    "last_sale_date": None,
                },
            )
            row["units_90d"] += quantity
            row["revenue_90d"] += amount
            if doc_date >= cutoff_30:
                row["units_30d"] += quantity
                row["revenue_30d"] += amount
            if row["last_sale_date"] is None or doc_date > row["last_sale_date"]:
                row["last_sale_date"] = doc_date
    return stats


async def replace_stats(session: AsyncSession, stats: dict) -> int:
    await session.execute(delete(ProductSalesStat))
    for sku, row in stats.items():
        session.add(
            ProductSalesStat(
                sku=sku,
                units_30d=row["units_30d"],
                revenue_30d=row["revenue_30d"],
                units_90d=row["units_90d"],
                revenue_90d=row["revenue_90d"],
                last_sale_date=row["last_sale_date"],
            )
        )
    await session.commit()
    return len(stats)


async def best_sellers(
    session: AsyncSession,
    *,
    category: str | None = None,
    limit: int = 5,
) -> list[dict]:
    stmt = (
        select(ProductSalesStat, CatalogItem)
        .join(CatalogItem, CatalogItem.sku == ProductSalesStat.sku)
        .where(
            CatalogItem.active.is_(True),
            CatalogItem.stock > 0,
            ProductSalesStat.units_90d > 0,
        )
        .order_by(ProductSalesStat.units_30d.desc(), ProductSalesStat.revenue_30d.desc())
        .limit(max(int(limit), 1))
    )
    if category:
        stmt = stmt.where(CatalogItem.category.ilike(f"%{category}%"))
    rows = (await session.execute(stmt)).all()
    return [
        {
            "sku": item.sku,
            "name": item.name,
            "category": item.category,
            "price": str(item.price),
            "currency": item.currency,
            "units_30d": stat.units_30d,
            "revenue_30d": str(stat.revenue_30d),
            "units_90d": stat.units_90d,
            "last_sale_date": (
                stat.last_sale_date.isoformat() if stat.last_sale_date else None
            ),
        }
        for stat, item in rows
    ]
