from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Contact, Payment, PaymentEvent
from app.payments import verify_standard_webhook
from app.sap import MockSap
from app.services import cart as cart_service
from app.services.orders import create_order


def _signature(secret_key: bytes, message_id: str, timestamp: str, body: bytes) -> str:
    signed = f"{message_id}.{timestamp}.{body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret_key, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


def test_standard_webhook_signature():
    secret_key = b"clave-de-prueba"
    secret = "whsec_" + base64.b64encode(secret_key).decode("ascii")
    message_id = "msg_123"
    timestamp = str(int(time.time()))
    body = b'{"event":"qr.paid","data":{"qrId":"1"}}'
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _signature(secret_key, message_id, timestamp, body),
    }
    assert verify_standard_webhook(headers, body, secret)


def test_standard_webhook_rejects_tampered_body():
    secret_key = b"clave-de-prueba"
    secret = "whsec_" + base64.b64encode(secret_key).decode("ascii")
    message_id = "msg_123"
    timestamp = str(int(time.time()))
    body = b'{"event":"qr.paid"}'
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _signature(secret_key, message_id, timestamp, body),
    }
    assert not verify_standard_webhook(headers, body + b"x", secret)


def test_standard_webhook_rejects_expired_timestamp():
    secret_key = b"clave-de-prueba"
    secret = "whsec_" + base64.b64encode(secret_key).decode("ascii")
    message_id = "msg_123"
    timestamp = str(int(time.time()) - 3600)
    body = b'{"event":"qr.paid"}'
    headers = {
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _signature(secret_key, message_id, timestamp, body),
    }
    assert not verify_standard_webhook(headers, body, secret)


async def test_cucu_webhook_confirms_payment(session, monkeypatch):
    secret_key = b"clave-cucu"
    secret = "whsec_" + base64.b64encode(secret_key).decode("ascii")
    monkeypatch.setattr(settings, "cucu_webhook_secret", secret)

    contact = Contact(wa_id="59179462889", phone_e164="+59179462889", name="Ana")
    session.add(contact)
    await session.commit()
    cart = await cart_service.get_or_create_cart(session, contact.id)
    await cart_service.add_item(session, cart, "FILT-001", 2)
    order, payment = await create_order(session, contact, cart, MockSap(session))

    payment.provider = "cucu_qr"
    payment.provider_ref = "qr_test_1"
    payment.raw = {"qrId": "qr_test_1"}
    await session.commit()

    body = json.dumps(
        {
            "event": "qr.paid",
            "data": {
                "qrId": "qr_test_1",
                "amount": "170.00",
                "currency": "BOB",
                "status": "PAID",
                "externalReference": order.number,
            },
        }
    ).encode()
    message_id = "msg_cucu_1"
    timestamp = str(int(time.time()))
    headers = {
        "content-type": "application/json",
        "webhook-id": message_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _signature(secret_key, message_id, timestamp, body),
    }

    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhooks/payments/cucu", content=body, headers=headers
            )
            assert response.status_code == 200
            assert response.json()["status"] == "ok"

            await session.refresh(payment)
            await session.refresh(order)
            assert payment.status == "paid"
            assert order.status == "invoiced"
            assert payment.invoice_doc_entry is not None
            events = await session.scalar(
                select(func.count()).select_from(PaymentEvent)
            )
            assert events == 1

            duplicate = await client.post(
                "/webhooks/payments/cucu", content=body, headers=headers
            )
            assert duplicate.status_code == 200
            assert duplicate.json()["status"] == "duplicate"
    finally:
        app.dependency_overrides.clear()
