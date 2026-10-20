"""Sincroniza estadísticas de ventas desde facturas de SAP.

Uso:
    python -m scripts.sync_sales_stats --days 90
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, timedelta

from app.config import settings
from app.db import SessionLocal, init_db
from app.sap import ServiceLayerSap
from app.services.sales_stats import aggregate_invoice_docs, replace_stats

logger = logging.getLogger("sync_sales_stats")
PAGE_SIZE = 20


async def run(days: int, max_invoices: int) -> None:
    await init_db()
    if settings.sap_mode != "service_layer":
        raise SystemExit("SAP_MODE debe ser service_layer")
    today = date.today()
    since = today - timedelta(days=days)
    sap = ServiceLayerSap(session=None)  # type: ignore[arg-type]
    docs: list[dict] = []
    skip = 0
    try:
        while len(docs) < max_invoices:
            data = await sap.get(
                "Invoices",
                params={
                    "$filter": (
                        f"DocDate ge datetime'{since.isoformat()}T00:00:00'"
                    ),
                    "$top": PAGE_SIZE,
                    "$skip": skip,
                    "$orderby": "DocDate asc",
                    "$select": "DocEntry,DocDate,DocumentLines",
                },
            )
            batch = data.get("value", [])
            if not batch:
                break
            docs.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
            logger.info("Facturas leídas: %s", len(docs))
    finally:
        await sap.close()

    stats = aggregate_invoice_docs(docs, today=today)
    async with SessionLocal() as session:
        count = await replace_stats(session, stats)
    logger.info("SKUs con ventas: %s (facturas: %s)", count, len(docs))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max-invoices", type=int, default=2000)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(args.days, args.max_invoices))


if __name__ == "__main__":
    main()
