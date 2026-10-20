"""Consumer logic for SAP outbox events published by the .NET integrator."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import CatalogItem, Contact, ProductPromotion, SapEventInbox, utcnow
from ..sap import (
    PricePeriod,
    QuantityTier,
    SapItem,
    ServiceLayerSap,
    get_sap,
)
from . import purchases

logger = logging.getLogger(__name__)


@dataclass
class SapEvent:
    event_id: str
    tenant_id: str
    event_type: str
    object_type: str
    aggregate_id: str
    occurred_at: datetime | None
    payload: str | None
    data: dict | None = None


def parse_event(data: dict) -> SapEvent:
    # MassTransit wraps the contract in { "message": { ... } }.
    if isinstance(data.get("message"), dict):
        data = data["message"]
    occurred = (
        data.get("occurred_at")
        or data.get("occurredAt")
        or data.get("OccurredAt")
    )
    parsed = None
    if occurred:
        try:
            parsed = datetime.fromisoformat(
                str(occurred).replace("Z", "+00:00")
            )
        except ValueError:
            parsed = None
    payload = data.get("payload", data.get("Payload"))
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload, ensure_ascii=False)
    normalized = data.get("data", data.get("Data"))
    if isinstance(normalized, str):
        try:
            normalized = json.loads(normalized)
        except json.JSONDecodeError:
            normalized = None
    if not isinstance(normalized, dict):
        normalized = None
    return SapEvent(
        event_id=str(
            data.get("event_id")
            or data.get("eventId")
            or data.get("EventId")
            or ""
        ),
        tenant_id=str(
            data.get("tenant_id")
            or data.get("tenantId")
            or data.get("TenantId")
            or ""
        ),
        event_type=str(
            data.get("event_type")
            or data.get("eventType")
            or data.get("EventType")
            or ""
        ),
        object_type=str(
            data.get("object_type")
            or data.get("objectType")
            or data.get("ObjectType")
            or ""
        ),
        aggregate_id=str(
            data.get("aggregate_id")
            or data.get("aggregateId")
            or data.get("AggregateId")
            or ""
        ),
        occurred_at=parsed,
        payload=payload if payload is not None else None,
        data=normalized,
    )


async def _sync_item(session: AsyncSession, event: SapEvent) -> dict:
    sku = event.aggregate_id.strip()
    if not sku:
        return {"status": "ignored", "reason": "missing_item_code"}

    data = event.data or {}
    if data.get("sku") and data.get("name"):
        item = SapItem(
            sku=str(data["sku"]),
            name=str(data["name"]),
            price=Decimal(str(data.get("price") or 0)),
            stock=int(data.get("stock") or 0),
            currency=str(data.get("currency") or "BOB"),
            stock_by_store={
                str(key): int(value)
                for key, value in (data.get("stock_by_store") or {}).items()
            },
        )
    else:
        sap = get_sap(session)
        item = await sap.get_item(sku)
    if item is None:
        return {"status": "ignored", "reason": "item_not_found"}

    row = await session.scalar(
        select(CatalogItem).where(CatalogItem.sku == item.sku)
    )
    if row is None:
        row = CatalogItem(
            sku=item.sku,
            name=item.name,
            price=Decimal(item.price),
            stock=item.stock,
            currency=item.currency,
        )
        session.add(row)
    else:
        row.name = item.name
        row.price = Decimal(item.price)
        row.stock = item.stock
        row.currency = item.currency
        row.active = True
        row.sap_valid = True
    await session.commit()
    return {"status": "processed", "sku": item.sku}


async def _sync_invoice(session: AsyncSession, event: SapEvent) -> dict:
    try:
        doc_entry = int(event.aggregate_id)
    except (TypeError, ValueError):
        return {"status": "ignored", "reason": "invalid_doc_entry"}
    sap = get_sap(session)
    try:
        result = await purchases.sync_invoice_by_doc_entry(
            session, sap, doc_entry
        )
    finally:
        close = getattr(sap, "close", None)
        if close is not None:
            await close()
    if not result.get("ok"):
        return {
            "status": "ignored",
            "reason": result.get("reason") or "invoice_not_applied",
        }
    return {"status": "processed", **result}


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_key_values(event: SapEvent) -> tuple[str, dict[str, str]]:
    """Extrae ItemCode/CardCode del payload del outbox de SpecialPrices."""
    try:
        payload = json.loads(event.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    columns = [
        part.strip()
        for part in str(payload.get("keyColumns") or "").split(",")
        if part.strip()
    ]
    raw_values = str(payload.get("keyValues") or event.aggregate_id or "")
    try:
        values = next(csv.reader([raw_values], delimiter="\t" if "\t" in raw_values else ","))
    except (csv.Error, StopIteration):
        values = [raw_values]
    values = [value.strip().strip("'\"") for value in values]
    data = dict(zip(columns, values))
    sku = (
        data.get("ItemCode")
        or data.get("itemCode")
        or (values[0] if len(values) == 1 else "")
    )
    if not sku:
        match = re.search(r"[A-Z0-9][A-Z0-9_-]{3,}", raw_values.upper())
        sku = match.group(0) if match else ""
    return sku.strip().upper(), data


async def _sync_customer(session: AsyncSession, event: SapEvent) -> dict:
    card_code = (event.aggregate_id or "").strip()
    if not card_code:
        return {"status": "ignored", "reason": "missing_card_code"}
    contact = await session.scalar(
        select(Contact).where(Contact.sap_card_code == card_code)
    )
    if contact is None:
        return {"status": "ignored", "reason": "contact_not_linked"}
    sap = get_sap(session)
    if event.data and (event.data.get("CardName") or event.data.get("cardName")):
        data = event.data
    else:
        try:
            data = await sap.get(f"BusinessPartners('{card_code}')")
        finally:
            close = getattr(sap, "close", None)
            if close is not None:
                await close()
    if data.get("CardName") or data.get("cardName"):
        contact.name = str(data.get("CardName") or data.get("cardName"))[:200]
    if data.get("FederalTaxID") or data.get("federalTaxId"):
        contact.tax_id = str(
            data.get("FederalTaxID") or data.get("federalTaxId")
        )[:40]
    await session.commit()
    return {"status": "processed", "card_code": card_code}


async def _sync_special_price(session: AsyncSession, event: SapEvent) -> dict:
    normalized = event.data or {}
    if normalized.get("periods") is not None:
        sku = str(normalized.get("sku") or event.aggregate_id).strip().upper()
        card_code = str(normalized.get("card_code") or "*1")
        periods = [
            PricePeriod(
                valid_from=_as_date(period.get("valid_from")),
                valid_to=_as_date(period.get("valid_to")),
                price=(
                    Decimal(str(period["price"]))
                    if period.get("price") is not None
                    else None
                ),
                discount_percent=Decimal(
                    str(period.get("discount_percent") or 0)
                ),
                price_list=int(period.get("price_list") or 1),
                tiers=[
                    QuantityTier(
                        quantity=int(tier.get("quantity") or 0),
                        price=Decimal(str(tier.get("price") or 0)),
                        discount_percent=Decimal(
                            str(tier.get("discount_percent") or 0)
                        ),
                    )
                    for tier in period.get("tiers") or []
                ],
            )
            for period in normalized.get("periods") or []
        ]
    else:
        sku, keys = _parse_key_values(event)
        card_code = str(keys.get("CardCode") or keys.get("cardCode") or "")
        if not sku:
            return {"status": "ignored", "reason": "missing_item_code"}
        sap = get_sap(session)
        getter = getattr(sap, "get_price_periods", None)
        if getter is None:
            return {"status": "ignored", "reason": "pricing_not_supported"}
        periods = await getter(sku, force_refresh=True)

    if card_code and card_code not in {"*1", "*"}:
        return {"status": "ignored", "reason": "customer_specific_price"}
    if not sku:
        return {"status": "ignored", "reason": "missing_item_code"}

    today = date.today()

    await session.execute(
        delete(ProductPromotion).where(
            ProductPromotion.sku == sku,
            ProductPromotion.source == "sap_special_price",
        )
    )
    inserted = 0
    for period in periods:
        if period.valid_to is not None and period.valid_to < today:
            continue
        if period.price is not None and period.price > 0:
            session.add(
                ProductPromotion(
                    sku=sku,
                    price=Decimal(period.price),
                    discount_percent=Decimal(period.discount_percent or 0),
                    valid_from=period.valid_from,
                    valid_to=period.valid_to,
                    tier_quantity=None,
                    price_list=period.price_list,
                    source="sap_special_price",
                    synced_at=utcnow(),
                )
            )
            inserted += 1
        for tier in period.tiers:
            session.add(
                ProductPromotion(
                    sku=sku,
                    price=Decimal(tier.price),
                    discount_percent=Decimal(tier.discount_percent or 0),
                    valid_from=period.valid_from,
                    valid_to=period.valid_to,
                    tier_quantity=tier.quantity,
                    price_list=period.price_list,
                    source="sap_special_price",
                    synced_at=utcnow(),
                )
            )
            inserted += 1
    await session.commit()
    return {"status": "processed", "sku": sku, "promotions": inserted}


async def _dispatch(session: AsyncSession, event: SapEvent) -> dict:
    if settings.sap_event_tenant and event.tenant_id.lower() not in {
        "",
        settings.sap_event_tenant.lower(),
    }:
        return {"status": "ignored", "reason": "other_tenant"}
    if event.object_type == "2":
        return await _sync_customer(session, event)
    if event.object_type == "4":
        return await _sync_item(session, event)
    if event.object_type == "7":
        return await _sync_special_price(session, event)
    if event.object_type == "13":
        return await _sync_invoice(session, event)
    if event.object_type == "17":
        return {"status": "ignored", "reason": "order_status_not_implemented"}
    if event.object_type in {"PRICE_LIST", "PRICE_LIST_HEADER"}:
        return {
            "status": "ignored",
            "reason": "price_list_uses_scheduled_sync",
        }
    return {"status": "ignored", "reason": "unsupported_object_type"}


async def process_sap_event(session: AsyncSession, data: dict) -> dict:
    event = parse_event(data)
    if not event.event_id:
        raise ValueError("Evento SAP sin event_id")

    inbox = await session.get(SapEventInbox, event.event_id)
    if inbox and inbox.processed_at is not None:
        return {"status": "duplicate", "event_id": event.event_id}
    if inbox is None:
        inbox = SapEventInbox(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            object_type=event.object_type,
            aggregate_id=event.aggregate_id,
            occurred_at=event.occurred_at,
        )
        session.add(inbox)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"status": "duplicate", "event_id": event.event_id}
    else:
        inbox.attempts += 1
        inbox.error = None
        await session.commit()

    try:
        result = await _dispatch(session, event)
    except Exception as exc:  # noqa: BLE001 - el consumer decide reintento
        inbox = await session.get(SapEventInbox, event.event_id)
        if inbox:
            inbox.attempts += 1
            inbox.error = str(exc)[:2000]
            await session.commit()
        logger.exception("Error procesando evento SAP %s", event.event_id)
        raise

    inbox = await session.get(SapEventInbox, event.event_id)
    if inbox:
        inbox.processed_at = datetime.now(timezone.utc)
        if result.get("status") == "ignored":
            inbox.error = str(result.get("reason") or "ignored")[:2000]
        await session.commit()
    logger.info("Evento SAP %s: %s", event.event_id, result.get("status"))
    return {
        "status": result.get("status", "processed"),
        "event_id": event.event_id,
        **{k: v for k, v in result.items() if k != "status"},
    }
