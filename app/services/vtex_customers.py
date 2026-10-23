"""Clientes y compras VTEX para el flujo conversacional del bot.

Se usa cuando ``SAP_MODE=vtex``. No reemplaza al servicio SAP: el bot conserva
ambas ramas y elige según el adaptador que devuelve ``get_sap``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogItem,
    Contact,
    CustomerFact,
    CustomerProfile,
    PurchaseHistory,
    PurchaseHistoryLine,
)

logger = logging.getLogger(__name__)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _full_name(raw: dict) -> str | None:
    parts = [
        str(raw.get("firstName") or "").strip(),
        str(raw.get("lastName") or "").strip(),
    ]
    name = " ".join(part for part in parts if part).strip()
    return name[:120] or None


def _mask_name(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return " ".join(part[0] + "***" for part in parts[:4])


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
    session: AsyncSession, contact_id: str, key: str, value, *, source: str = "vtex"
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


async def find_candidates(
    sap, document: str, limit: int = 5
) -> list[dict]:
    """Busca un cliente VTEX por documento y devuelve candidatos."""
    term = (document or "").strip()
    if not term:
        return []
    raw = await sap.get_customer(term)
    if not raw:
        return []
    doc = str(raw.get("document") or "").strip()
    if not doc:
        return []
    name = _full_name(raw) or doc
    return [
        {
            "card_code": doc[:20],
            "name": name,
            "name_masked": _mask_name(name),
            "card_type": "VTEX",
            "has_phone": bool(raw.get("phone")),
            "has_email": bool(raw.get("email")),
        }
    ][:limit]


async def _update_profile(
    session: AsyncSession, contact: Contact, raw: dict
) -> None:
    name = _full_name(raw)
    document = str(raw.get("document") or "").strip()
    phone = _digits(raw.get("phone"))

    if name and (not contact.name or contact.name == contact.tax_id):
        contact.name = name[:120]
    if document and not contact.tax_id:
        contact.tax_id = document[:20]
    if phone and len(phone) >= 8 and not contact.phone_e164:
        contact.phone_e164 = f"+{phone}"[:32]

    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    if profile is None:
        profile = CustomerProfile(contact_id=contact.id, preferences={})
        session.add(profile)

    preferences = dict(profile.preferences or {})
    preferences["vtex"] = {
        "source": "vtex",
        "vtex_customer_id": raw.get("id"),
        "email": raw.get("email"),
        "document": raw.get("document"),
        "phone": raw.get("phone"),
        "first_name": raw.get("firstName"),
        "last_name": raw.get("lastName"),
        "is_corporate": raw.get("isCorporate"),
        "corporate_name": raw.get("corporateName"),
        "trade_name": raw.get("tradeName"),
        "state_inscription": raw.get("stateInscription"),
    }
    profile.preferences = preferences

    await _set_fact(session, contact.id, "vtex_customer_id", raw.get("id"))
    await _set_fact(session, contact.id, "email", raw.get("email"))
    await _set_fact(session, contact.id, "document", raw.get("document"))
    await _set_fact(session, contact.id, "phone", raw.get("phone"))
    await _set_fact(session, contact.id, "is_corporate", raw.get("isCorporate"))
    await _set_fact(session, contact.id, "corporate_name", raw.get("corporateName"))
    await _set_fact(session, contact.id, "trade_name", raw.get("tradeName"))
    await _set_fact(
        session, contact.id, "state_inscription", raw.get("stateInscription")
    )


async def _enrich_from_order(
    session: AsyncSession, contact: Contact, detail: dict
) -> None:
    client = detail.get("clientProfileData") or {}
    phone = _digits(client.get("phone"))
    first_name = str(client.get("firstName") or "").strip()
    last_name = str(client.get("lastName") or "").strip()
    order_name = " ".join(
        part for part in (first_name, last_name) if part
    ).strip()

    if phone and len(phone) >= 8 and not contact.phone_e164:
        contact.phone_e164 = f"+{phone}"[:32]
    if order_name and (not contact.name or contact.name == contact.tax_id):
        contact.name = order_name[:120]
    document = str(client.get("document") or "").strip()
    if document and not contact.tax_id:
        contact.tax_id = document[:20]

    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    if profile is None:
        profile = CustomerProfile(contact_id=contact.id, preferences={})
        session.add(profile)
    preferences = dict(profile.preferences or {})
    vtex = dict(preferences.get("vtex") or {})
    address = (detail.get("shippingData") or {}).get("address") or {}
    if address:
        vtex["last_order_address"] = address
    if phone:
        vtex["phone"] = f"+{phone}"
    preferences["vtex"] = vtex
    profile.preferences = preferences

    if phone:
        await _set_fact(session, contact.id, "phone", f"+{phone}")
    if document:
        await _set_fact(session, contact.id, "document", document)


async def _sync_orders(
    session: AsyncSession,
    contact: Contact,
    sap,
    terms: list[str],
    max_orders: int,
) -> int:
    orders: list[dict] = []
    for term in dict.fromkeys(t for t in terms if t):
        skip = 0
        local: list[dict] = []
        while len(local) < max_orders:
            batch = await sap.get_customer_purchases(
                term,
                top=min(100, max_orders - len(local)),
                skip=skip,
            )
            if not batch:
                break
            local.extend(batch)
            if len(batch) < 100:
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
    for order in orders:
        order_id = str(order.get("orderId") or "").strip()
        try:
            detail = await sap.get_order(order_id) if order_id else {}
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo leer el pedido VTEX %s", order_id)
            detail = {}

        await _enrich_from_order(session, contact, detail)

        sequence = order.get("sequence") or detail.get("sequence") or order_id
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


async def sync_contact(
    session: AsyncSession,
    contact: Contact,
    sap,
    *,
    document: str | None = None,
    max_orders: int = 100,
) -> int:
    """Actualiza la ficha VTEX del contacto y reemplaza sus compras VTEX."""
    terms = [
        (document or "").strip(),
        (contact.tax_id or "").strip(),
        (contact.sap_card_code or "").strip(),
    ]
    raw = None
    for term in dict.fromkeys(t for t in terms if t):
        raw = await sap.get_customer(term)
        if raw:
            break

    if raw:
        await _update_profile(session, contact, raw)
        terms.extend(
            [
                str(raw.get("document") or "").strip(),
                str(raw.get("email") or "").strip(),
            ]
        )

    inserted = await _sync_orders(
        session, contact, sap, terms, max_orders
    )
    await session.commit()
    return inserted
