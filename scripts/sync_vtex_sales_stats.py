"""Calcula los más vendidos del bot a partir de pedidos VTEX.

No usa SAP. Recorre OMS, lee el detalle de cada pedido y agrega unidades e
ingresos por SKU para 30/90 días en ``product_sales_stats``.

Uso:
    python -m scripts.sync_vtex_sales_stats
    python -m scripts.sync_vtex_sales_stats --days 90 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.config import settings
from app.db import SessionLocal, init_db
from app.sap import get_sap
from app.services.sales_stats import replace_stats

logger = logging.getLogger("sync_vtex_sales_stats")
PAGE_SIZE = 100


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


async def sync(days: int = 90, limit_orders: int | None = None, dry_run: bool = False) -> None:
    if settings.sap_mode != "vtex":
        raise SystemExit("SAP_MODE debe ser 'vtex' para calcular ventas desde VTEX")

    await init_db()
    today = date.today()
    cutoff_90 = today - timedelta(days=max(days, 90))
    cutoff_30 = today - timedelta(days=30)
    created_from = f"{cutoff_90.isoformat()}T00:00:00.000Z"
    created_to = f"{today.isoformat()}T23:59:59.999Z"

    stats: dict[str, dict] = {}
    seen_orders = 0
    seen_lines = 0
    page = 1

    async with SessionLocal() as session:
        sap = get_sap(session)
        try:
            while True:
                data = await sap.get_orders_page(
                    page=page,
                    per_page=PAGE_SIZE,
                    created_from=created_from,
                    created_to=created_to,
                )
                orders = data.get("list") or []
                paging = data.get("paging") or {}
                if not orders:
                    break

                for order in orders:
                    if limit_orders and seen_orders >= limit_orders:
                        break
                    if str(order.get("status") or "").lower() == "canceled":
                        continue

                    order_id = str(order.get("orderId") or "").strip()
                    if not order_id:
                        continue

                    try:
                        detail = await sap.get_order(order_id)
                    except Exception:  # noqa: BLE001
                        logger.exception("No se pudo leer el pedido %s", order_id)
                        continue

                    order_date = _as_date(
                        order.get("creationDate") or detail.get("creationDate")
                    )
                    if order_date is None or order_date < cutoff_90:
                        continue

                    seen_orders += 1
                    for item in detail.get("items") or []:
                        sku = str(item.get("refId") or item.get("id") or "").strip()
                        if not sku:
                            continue
                        try:
                            quantity = int(float(item.get("quantity") or 0))
                        except (TypeError, ValueError):
                            quantity = 0
                        if quantity <= 0:
                            continue

                        unit_price = Decimal(
                            str(item.get("price") or item.get("sellingPrice") or 0)
                        )
                        amount = (unit_price * quantity / 100).quantize(
                            Decimal("0.01")
                        )
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
                        if order_date >= cutoff_30:
                            row["units_30d"] += quantity
                            row["revenue_30d"] += amount
                        if (
                            row["last_sale_date"] is None
                            or order_date > row["last_sale_date"]
                        ):
                            row["last_sale_date"] = order_date
                        seen_lines += 1

                logger.info(
                    "Ventas VTEX: página %s, %s pedidos, %s líneas, %s SKU",
                    page,
                    seen_orders,
                    seen_lines,
                    len(stats),
                )
                if limit_orders and seen_orders >= limit_orders:
                    break
                total_pages = int(paging.get("pages") or 0)
                if total_pages and page >= total_pages:
                    break
                page += 1

            logger.info(
                "Ventas VTEX listas: %s pedidos, %s SKU", seen_orders, len(stats)
            )
            if dry_run:
                return
            if not stats:
                logger.warning("No hay ventas para guardar; no se toca la tabla")
                return
            count = await replace_stats(session, stats)
            logger.info("Estadísticas de ventas guardadas: %s SKU", count)
        finally:
            await sap.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calcula más vendidos desde pedidos VTEX"
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--limit-orders", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(
        sync(
            days=args.days,
            limit_orders=args.limit_orders,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
