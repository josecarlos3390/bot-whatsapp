"""RFM and commercial analysis for a linked customer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PurchaseHistory, PurchaseHistoryLine
from .purchases import history_summary


async def analyze_customer(session: AsyncSession, contact_id: str) -> dict:
    summary = await history_summary(session, contact_id)
    count = int(summary["count"])
    total = Decimal(summary["total"] or 0)
    last_date = (
        date.fromisoformat(summary["last_purchase"])
        if summary["last_purchase"]
        else None
    )
    first_date = await session.scalar(
        select(func.min(PurchaseHistory.doc_date)).where(
            PurchaseHistory.contact_id == contact_id
        )
    )
    recency_days = (date.today() - last_date).days if last_date else None
    avg_ticket = (
        (total / count).quantize(Decimal("0.01")) if count else Decimal("0")
    )

    if count == 0:
        segment = "sin_compras"
    elif recency_days is not None and recency_days > 180:
        segment = "inactivo"
    elif recency_days is not None and recency_days > 90:
        segment = "en_riesgo"
    elif total >= 5000 or count >= 5:
        segment = "alto_valor"
    elif count >= 3:
        segment = "recurrente"
    elif count == 1:
        segment = "nuevo"
    else:
        segment = "activo"

    return {
        "frequency": count,
        "monetary": str(total),
        "avg_ticket": str(avg_ticket),
        "last_purchase": summary["last_purchase"],
        "first_purchase": first_date.isoformat() if first_date else None,
        "recency_days": recency_days,
        "top_categories": summary["top_categories"],
        "segment": segment,
    }


async def analysis_text(session: AsyncSession, contact_id: str) -> str:
    analysis = await analyze_customer(session, contact_id)
    if analysis["frequency"] == 0:
        return ""
    categories = ", ".join(
        row["category"] for row in analysis["top_categories"][:3]
    )
    return (
        f"Cliente {analysis['segment']}: {analysis['frequency']} compras, "
        f"Bs {analysis['monetary']}, ticket promedio Bs "
        f"{analysis['avg_ticket']}, última {analysis['last_purchase']}"
        + (f", categorías: {categories}" if categories else "")
    )
