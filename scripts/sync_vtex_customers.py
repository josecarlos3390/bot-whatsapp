"""Migra clientes y compras de VTEX a la base local del bot.

Uso:
    python -m scripts.sync_vtex_customers
    python -m scripts.sync_vtex_customers --limit 100
    python -m scripts.sync_vtex_customers --no-purchases

Requiere SAP_MODE=vtex y PaasVTEX con /api/vtex/customers/export.
No escribe en VTEX: solo lee clientes (Master Data CL) y pedidos (OMS).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import (
    CatalogItem,
    Contact,
    CustomerFact,
    CustomerProfile,
    PurchaseHistory,
    PurchaseHistoryLine,
)
from app.sap import SapNotFound, get_sap

logger = logging.getLogger("sync_vtex_customers")
PAGE_SIZE = 500
ORDER_PAGE_SIZE = 100


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _full_name(row: dict) -> str | None:
    parts = [
        str(row.get("first_name") or "").strip(),
        str(row.get("last_name") or "").strip(),
    ]
    name = " ".join(part for part in parts if part).strip()
    return name[:120] or None


def _wa_id(row: dict) -> str | None:
    phone = _digits(row.get("phone"))
    if len(phone) >= 8:
        return phone[:32]

    document = str(row.get("document") or "").strip()
    if document:
        return f"vtex:{document[:26]}"

    email = str(row.get("email") or "").strip().lower()
    if email:
        digest = hashlib.sha1(email.encode("utf-8")).hexdigest()[:24]
        return f"vtex:{digest}"

    customer_id = str(row.get("id") or "").strip()
    if customer_id:
        digest = hashlib.sha1(customer_id.encode("utf-8")).hexdigest()[:24]
        return f"vtex:{digest}"

    return None


def _phone_e164(row: dict) -> str:
    phone = _digits(row.get("phone"))
    if len(phone) < 8:
        return ""
    return f"+{phone}"[:32]


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


def _stable_int(value: str) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) & 0x7FFFFFFF


async def _set_fact(
    session, contact_id: str, key: str, value, *, source: str = "vtex"
) -> None:
    if value in (None, ""):
        return
    row = await session.scalar(
        select(CustomerFact).where(
            CustomerFact.contact_id == contact_id,
            CustomerFact.key == key,
        )
    )
    if row is None:
        session.add(
            CustomerFact(
                contact_id=contact_id,
                key=key,
                value=str(value)[:4000],
                source=source,
            )
        )
    else:
        row.value = str(value)[:4000]
        row.source = source


async def _upsert_customer(session, row: dict) -> Contact | None:
    wa_id = _wa_id(row)
    if not wa_id:
        return None

    document = str(row.get("document") or "").strip()[:20] or None
    phone = _phone_e164(row)
    name = _full_name(row)

    contact = await session.scalar(
        select(Contact).where(Contact.wa_id == wa_id)
    )
    if contact is None and document:
        contact = await session.scalar(
            select(Contact).where(Contact.tax_id == document)
        )
    if contact is None:
        contact = Contact(
            wa_id=wa_id,
            phone_e164=phone,
            name=name,
            tax_id=document,
            opt_in=True,
        )
        session.add(contact)
        await session.flush()
    else:
        if name and not contact.name:
            contact.name = name
        if document and not contact.tax_id:
            contact.tax_id = document
        if phone and not contact.phone_e164:
            contact.phone_e164 = phone

    vtex_data = {
        "source": "vtex",
        "vtex_customer_id": row.get("id"),
        "email": row.get("email"),
        "document": row.get("document"),
        "phone": row.get("phone"),
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "is_corporate": row.get("is_corporate"),
        "corporate_name": row.get("corporate_name"),
        "trade_name": row.get("trade_name"),
        "state_inscription": row.get("state_inscription"),
    }

    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    if profile is None:
        profile = CustomerProfile(
            contact_id=contact.id,
            preferences={"vtex": vtex_data},
        )
        session.add(profile)
    else:
        preferences = dict(profile.preferences or {})
        preferences["vtex"] = vtex_data
        profile.preferences = preferences

    await _set_fact(session, contact.id, "vtex_customer_id", row.get("id"))
    await _set_fact(session, contact.id, "email", row.get("email"))
    await _set_fact(session, contact.id, "document", row.get("document"))
    await _set_fact(session, contact.id, "phone", row.get("phone"))
    await _set_fact(session, contact.id, "is_corporate", row.get("is_corporate"))
    await _set_fact(session, contact.id, "corporate_name", row.get("corporate_name"))
    await _set_fact(session, contact.id, "trade_name", row.get("trade_name"))
    await _set_fact(
        session, contact.id, "state_inscription", row.get("state_inscription")
    )

    return contact


async def _enrich_from_order(
    session, contact: Contact, profile: CustomerProfile | None, detail: dict
) -> None:
    """Completa teléfono/nombre/email/última dirección desde el pedido OMS."""
    client = detail.get("clientProfileData") or {}
    phone = _digits(client.get("phone"))
    first_name = str(client.get("firstName") or "").strip()
    last_name = str(client.get("lastName") or "").strip()
    order_name = " ".join(
        part for part in (first_name, last_name) if part
    ).strip()

    if phone and len(phone) >= 8 and not contact.phone_e164:
        contact.phone_e164 = f"+{phone}"[:32]
        if contact.wa_id.startswith("vtex:"):
            existing = await session.scalar(
                select(Contact).where(
                    Contact.wa_id == phone[:32],
                    Contact.id != contact.id,
                )
            )
            if existing is None:
                contact.wa_id = phone[:32]

    if order_name and (not contact.name or contact.name == contact.tax_id):
        contact.name = order_name[:120]

    document = str(client.get("document") or "").strip()
    if document and not contact.tax_id:
        contact.tax_id = document[:20]

    if profile is None:
        profile = await session.scalar(
            select(CustomerProfile).where(
                CustomerProfile.contact_id == contact.id
            )
        )
    if profile is None:
        profile = CustomerProfile(
            contact_id=contact.id,
            preferences={},
        )
        session.add(profile)

    preferences = dict(profile.preferences or {})
    vtex = dict(preferences.get("vtex") or {})
    if phone:
        vtex["phone"] = f"+{phone}"
    email = str(client.get("email") or "").strip()
    if email and not email.endswith("@ct.vtex.com.br") and not vtex.get("email"):
        vtex["email"] = email
    address = (detail.get("shippingData") or {}).get("address") or {}
    if address:
        vtex["last_order_address"] = address
    preferences["vtex"] = vtex
    profile.preferences = preferences

    if phone:
        await _set_fact(session, contact.id, "phone", f"+{phone}")
    if email and not email.endswith("@ct.vtex.com.br"):
        await _set_fact(session, contact.id, "email", email)
    await _set_fact(session, contact.id, "document", document)


async def _order_history(
    session, contact: Contact, sap, max_orders: int
) -> int:
    terms = [
        str(value).strip()
        for value in (contact.tax_id,)
        if value and str(value).strip()
    ]
    if not terms:
        facts = (
            await session.scalars(
                select(CustomerFact).where(
                    CustomerFact.contact_id == contact.id,
                    CustomerFact.key == "email",
                )
            )
        ).all()
        terms = [fact.value for fact in facts if fact.value]

    orders: list[dict] = []
    for term in terms:
        skip = 0
        local: list[dict] = []
        while len(local) < max_orders:
            try:
                batch = await sap.get_customer_purchases(
                    term,
                    top=min(ORDER_PAGE_SIZE, max_orders - len(local)),
                    skip=skip,
                )
            except SapNotFound:
                logger.info(
                    "Cliente/documento %s sin compras en VTEX; se omite",
                    term,
                )
                break
            if not batch:
                break
            local.extend(batch)
            if len(batch) < ORDER_PAGE_SIZE:
                break
            skip += len(batch)
        if local:
            orders = local
            break

    old_ids = select(PurchaseHistory.id).where(
        PurchaseHistory.contact_id == contact.id,
        PurchaseHistory.doc_type == "vtex_order",
    )
    await session.execute(
        delete(PurchaseHistoryLine).where(
            PurchaseHistoryLine.history_id.in_(old_ids)
        )
    )
    await session.execute(
        delete(PurchaseHistory).where(
            PurchaseHistory.contact_id == contact.id,
            PurchaseHistory.doc_type == "vtex_order",
        )
    )

    inserted = 0
    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    for order in orders:
        order_id = str(order.get("orderId") or "").strip()
        detail = await sap.get_order(order_id) if order_id else {}
        await _enrich_from_order(session, contact, profile, detail)
        sequence = (
            order.get("sequence")
            or detail.get("sequence")
            or order_id
        )
        try:
            doc_entry = int(sequence)
        except (TypeError, ValueError):
            doc_entry = _stable_int(str(sequence))

        doc_date = _as_date(
            order.get("creationDate") or detail.get("creationDate")
        )
        if doc_date is None:
            continue

        total = Decimal(str(order.get("totalValue") or 0))
        if total == 0:
            raw_value = detail.get("value")
            if raw_value not in (None, ""):
                total = Decimal(str(raw_value)) / 100

        currency = (
            order.get("currencyCode")
            or (detail.get("storePreferencesData") or {}).get("currencyCode")
            or "BOB"
        )

        history = PurchaseHistory(
            contact_id=contact.id,
            sap_doc_entry=doc_entry,
            doc_type="vtex_order",
            doc_num=doc_entry,
            doc_date=doc_date,
            total=total,
            currency=currency,
            synced_at=datetime.now(timezone.utc),
        )
        session.add(history)
        await session.flush()

        items = detail.get("items") or []
        skus = {
            str(item.get("refId") or item.get("id"))
            for item in items
            if item.get("refId") or item.get("id")
        }
        categories: dict[str, str | None] = {}
        if skus:
            rows = await session.execute(
                select(CatalogItem.sku, CatalogItem.category).where(
                    CatalogItem.sku.in_(skus)
                )
            )
            categories = {sku: category for sku, category in rows.all()}

        for item in items:
            sku = str(item.get("refId") or item.get("id") or "").strip()
            if not sku:
                continue
            quantity = Decimal(str(item.get("quantity") or 1))
            unit_price = Decimal(
                str(item.get("price") or item.get("sellingPrice") or 0)
            )
            amount = (unit_price * quantity / 100).quantize(Decimal("0.01"))
            session.add(
                PurchaseHistoryLine(
                    history_id=history.id,
                    sku=sku[:64],
                    name=str(item.get("name") or "")[:200] or None,
                    category=categories.get(sku),
                    quantity=quantity,
                    amount=amount,
                )
            )
        inserted += 1

    return inserted


def _from_cl(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "email": row.get("email"),
        "document": row.get("document"),
        "first_name": row.get("firstName"),
        "last_name": row.get("lastName"),
        "phone": row.get("phone"),
        "is_corporate": row.get("isCorporate"),
        "corporate_name": row.get("corporateName"),
        "trade_name": row.get("tradeName"),
        "state_inscription": row.get("stateInscription"),
    }


async def _sync_contacts(
    session,
    sap,
    *,
    purchases: bool,
    max_orders: int,
    dry_run: bool,
) -> tuple[int, int]:
    contacts = (
        await session.scalars(
            select(Contact).where(Contact.tax_id.is_not(None))
        )
    ).all()
    migrated = 0
    orders = 0
    seen: set[str] = set()
    for contact in contacts:
        term = str(contact.tax_id or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        if dry_run:
            migrated += 1
            continue

        raw = await sap.get_customer(term)
        target = contact
        if raw:
            target = await _upsert_customer(session, _from_cl(raw)) or contact
        if purchases:
            orders += await _order_history(session, target, sap, max_orders)
        migrated += 1

    if not dry_run:
        await session.commit()
    return migrated, orders


async def sync(
    limit: int | None = 100,
    purchases: bool = True,
    max_orders: int = 100,
    dry_run: bool = False,
    from_contacts: bool = False,
) -> None:
    if settings.sap_mode != "vtex":
        raise SystemExit(
            "SAP_MODE debe ser 'vtex' para migrar clientes desde PaasVTEX"
        )

    await init_db()
    customers = 0
    orders = 0
    token: str | None = None

    async with SessionLocal() as session:
        sap = get_sap(session)
        try:
            if from_contacts:
                customers, orders = await _sync_contacts(
                    session,
                    sap,
                    purchases=purchases,
                    max_orders=max_orders,
                    dry_run=dry_run,
                )
                logger.info(
                    "Contactos existentes sincronizados desde VTEX: %s · pedidos: %s",
                    customers,
                    orders,
                )
                return

            while True:
                page = await sap.scroll_customers(token, PAGE_SIZE)
                rows = page.get("customers") or []
                token = page.get("token")
                if not rows:
                    break

                for row in rows:
                    if limit and customers >= limit:
                        break
                    if dry_run:
                        customers += 1
                        continue

                    contact = await _upsert_customer(session, row)
                    if contact is None:
                        continue
                    if purchases:
                        orders += await _order_history(
                            session, contact, sap, max_orders
                        )
                    customers += 1

                if not dry_run:
                    await session.commit()

                if limit and customers >= limit:
                    break
                if not token:
                    break

            logger.info(
                "Clientes VTEX migrados: %s · pedidos: %s", customers, orders
            )
        finally:
            await sap.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migra clientes y compras de VTEX a la base del bot"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Máximo de clientes VTEX (por defecto 100; usar --all para todos)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Recorre los 36k+ clientes de VTEX (usar con --no-purchases)",
    )
    parser.add_argument(
        "--from-contacts",
        action="store_true",
        help="Sincroniza solo los contactos ya existentes en el bot",
    )
    parser.add_argument(
        "--no-purchases",
        dest="purchases",
        action="store_false",
        help="Migra solo clientes, sin historial de pedidos",
    )
    parser.add_argument(
        "--max-orders",
        type=int,
        default=100,
        help="Máximo de pedidos por cliente",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.all and args.purchases:
        parser.error(
            "--all con historial haría una consulta OMS por cada uno de los "
            "36k+ clientes. Usá --all --no-purchases para la cartera completa, "
            "y --from-contacts (o --limit N) para las compras."
        )

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(
        sync(
            limit=None if args.all or args.from_contacts else args.limit,
            purchases=args.purchases,
            max_orders=args.max_orders,
            dry_run=args.dry_run,
            from_contacts=args.from_contacts,
        )
    )


if __name__ == "__main__":
    main()
