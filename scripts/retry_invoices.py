"""Reintenta la facturación de pedidos pagados que quedaron sin factura SAP.

Uso:
    python -m scripts.retry_invoices --limit 20

Sirve cuando la factura falló (por permisos de SAP, por un corte o porque el
integrador todavía no exponía el endpoint). Sólo toca pedidos en estado
``paid`` con nota de factura pendiente.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, engine, init_db
from app.models import Order
from app.sap import SapError, get_sap

logger = logging.getLogger("retry_invoices")


async def retry(limit: int) -> int:
    await init_db()
    processed = 0
    try:
        processed = await _retry(limit)
    finally:
        await engine.dispose()
    return processed


async def _retry(limit: int) -> int:
    async with SessionLocal() as session:
        order_ids = (
            await session.scalars(
                select(Order.id)
                .where(
                    Order.status == "paid",
                    Order.invoice_doc_entry.is_(None),
                    Order.notes.like("Factura SAP pendiente%"),
                )
                .order_by(Order.created_at)
                .limit(limit)
            )
        ).all()
    logger.info("Pedidos pendientes de facturar: %s", len(order_ids))

    processed = 0
    for order_id in order_ids:
        # Una sesión por pedido: un rollback no debe expirar los demás.
        async with SessionLocal() as session:
            order = await session.get(
                Order, order_id, options=[selectinload(Order.items)]
            )
            if order is None:
                continue
            number = order.number
            sap = get_sap(session)
            try:
                invoice = await sap.create_invoice_from_order(order)
                sap_payment = await sap.create_incoming_payment(order, invoice)
            except SapError as exc:
                logger.warning("Pedido %s sigue sin factura: %s", number, exc)
                continue
            except Exception:  # noqa: BLE001
                logger.exception("Error facturando %s", number)
                continue
            finally:
                await sap.close()

            order.status = "invoiced"
            order.invoice_doc_entry = invoice.doc_entry
            order.invoice_doc_num = invoice.doc_num
            order.sap_payment_doc_entry = (
                sap_payment.doc_entry if sap_payment else None
            )
            order.notes = (
                f"{order.notes}\nFactura regularizada: {invoice.doc_num}"
            )
            await session.commit()
            processed += 1
            logger.info(
                "Pedido %s facturado (DocEntry=%s)", number, invoice.doc_entry
            )

    return processed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reintenta facturar pedidos pagados sin factura"
    )
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    done = asyncio.run(retry(args.limit))
    logger.info("Facturados en esta pasada: %s", done)


if __name__ == "__main__":
    main()
