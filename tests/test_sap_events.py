from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import CatalogItem, Contact, PurchaseHistory, SapEventInbox
from app.services import sap_events
from app.sap import SapItem


@pytest.fixture(autouse=True)
def _sap_tenant(monkeypatch):
    monkeypatch.setattr(settings, "sap_event_tenant", "tenant-001")


class FakeSap:
    def __init__(self, item=None, invoice=None):
        self.item = item
        self.invoice = invoice

    async def get_item(self, sku):
        return self.item

    async def get(self, path, params=None):
        return self.invoice

    async def close(self):
        return None


def _item_event(event_id="evt-item-1", sku="NEW-SKU") -> dict:
    return {
        "event_id": event_id,
        "tenant_id": "tenant-001",
        "event_type": "Created",
        "object_type": "4",
        "aggregate_id": sku,
        "occurred_at": "2026-10-19T20:00:00Z",
    }


async def test_process_item_event(session, monkeypatch):
    monkeypatch.setattr(
        sap_events,
        "get_sap",
        lambda _: FakeSap(
            item=SapItem(
                sku="NEW-SKU",
                name="Producto nuevo",
                price=Decimal("99.90"),
                stock=7,
                currency="BOB",
            )
        ),
    )
    result = await sap_events.process_sap_event(session, _item_event())
    assert result["status"] == "processed"

    row = await session.scalar(
        select(CatalogItem).where(CatalogItem.sku == "NEW-SKU")
    )
    assert row is not None
    assert row.price == Decimal("99.90")
    assert row.stock == 7

    duplicate = await sap_events.process_sap_event(session, _item_event())
    assert duplicate["status"] == "duplicate"
    inbox = await session.get(SapEventInbox, "evt-item-1")
    assert inbox is not None and inbox.processed_at is not None


async def test_process_invoice_event_links_purchase(session, monkeypatch):
    contact = Contact(
        wa_id="59170000444",
        phone_e164="+59170000444",
        sap_card_code="C1",
    )
    session.add(contact)
    await session.commit()

    monkeypatch.setattr(
        sap_events,
        "get_sap",
        lambda _: FakeSap(
            invoice={
                "DocEntry": 9001,
                "DocNum": 9001,
                "DocDate": "2026-10-19T00:00:00Z",
                "DocTotal": 100,
                "DocCurrency": "BOB",
                "CardCode": "C1",
                "DocumentLines": [
                    {
                        "ItemCode": "FILT-001",
                        "ItemDescription": "Filtro",
                        "Quantity": 1,
                        "LineTotal": 85,
                    }
                ],
            }
        ),
    )
    result = await sap_events.process_sap_event(
        session,
        {
            "event_id": "evt-invoice-1",
            "tenant_id": "tenant-001",
            "event_type": "Created",
            "object_type": "13",
            "aggregate_id": "9001",
            "occurred_at": "2026-10-19T20:00:00Z",
        },
    )
    assert result["status"] == "processed"
    history = await session.scalar(
        select(PurchaseHistory).where(
            PurchaseHistory.contact_id == contact.id
        )
    )
    assert history is not None
    assert history.total == Decimal("100.00")


async def test_invoice_without_linked_contact_is_ignored(session, monkeypatch):
    monkeypatch.setattr(
        sap_events,
        "get_sap",
        lambda _: FakeSap(
            invoice={
                "DocEntry": 9002,
                "DocDate": "2026-10-19T00:00:00Z",
                "DocTotal": 10,
                "CardCode": "NO-LINK",
                "DocumentLines": [],
            }
        ),
    )
    result = await sap_events.process_sap_event(
        session,
        {
            "event_id": "evt-invoice-2",
            "tenant_id": "tenant-001",
            "event_type": "Created",
            "object_type": "13",
            "aggregate_id": "9002",
        },
    )
    assert result["status"] == "ignored"
    assert result["reason"] == "contact_not_linked"


def test_parse_event_pascal_case():
    event = sap_events.parse_event(
        {
            "EventId": "e2",
            "TenantId": "retail-qa5",
            "EventType": "Updated",
            "ObjectType": "7",
            "AggregateId": "SKU",
            "OccurredAt": "2026-10-19T20:00:00Z",
        }
    )
    assert event.event_id == "e2"
    assert event.tenant_id == "retail-qa5"
    assert event.object_type == "7"
    event = sap_events.parse_event(
        {
            "eventId": "e1",
            "tenantId": "t1",
            "eventType": "Created",
            "objectType": "4",
            "aggregateId": "SKU",
            "occurredAt": "2026-10-19T20:00:00Z",
        }
    )
    assert event.event_id == "e1"
    assert event.object_type == "4"
    assert event.occurred_at is not None
