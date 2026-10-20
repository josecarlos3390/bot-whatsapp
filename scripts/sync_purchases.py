"""Sincroniza facturas de SAP al historial local por cliente.

Uso:
    python -m scripts.sync_purchases --card-code VTX000019 --wa-id 59170000110
    python -m scripts.sync_purchases --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Contact
from app.sap import ServiceLayerSap
from app.services.purchases import sync_contact_purchases

logger = logging.getLogger("sync_purchases")


async def run(wa_id: str | None, card_code: str | None, name: str | None) -> None:
    await init_db()
    if settings.sap_mode != "service_layer":
        raise SystemExit("SAP_MODE debe ser service_layer para leer facturas")

    sap = ServiceLayerSap(session=None)  # type: ignore[arg-type]
    try:
        async with SessionLocal() as session:
            contacts: list[Contact]
            if wa_id or card_code:
                contact = None
                if wa_id:
                    contact = await session.scalar(
                        select(Contact).where(Contact.wa_id == wa_id)
                    )
                if contact is None and card_code:
                    contact = Contact(
                        wa_id=wa_id or f"card-{card_code}",
                        phone_e164=(wa_id or f"+{card_code}"),
                        name=name or card_code,
                        sap_card_code=card_code,
                    )
                    session.add(contact)
                    await session.commit()
                if contact is None:
                    raise SystemExit("No se encontró el contacto")
                if card_code and contact.sap_card_code != card_code:
                    contact.sap_card_code = card_code
                    await session.commit()
                contacts = [contact]
            else:
                contacts = list(
                    (
                        await session.scalars(
                            select(Contact).where(
                                Contact.sap_card_code.is_not(None)
                            )
                        )
                    ).all()
                )

            total = 0
            for contact in contacts:
                total += await sync_contact_purchases(
                    session, contact, sap
                )
            logger.info("Facturas sincronizadas: %s (%s clientes)", total, len(contacts))
    finally:
        await sap.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza compras SAP")
    parser.add_argument("--wa-id")
    parser.add_argument("--card-code")
    parser.add_argument("--name")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(args.wa_id, args.card_code, args.name))


if __name__ == "__main__":
    main()
