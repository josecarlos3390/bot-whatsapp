"""Proveedores de pago.

``mock_qr`` genera un QR local para desarrollo. ``cucu_qr`` integra el sandbox
de QR Simple de CUCU (Bolivia), que expone POST /qr y webhooks firmados.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Order, Payment, utcnow

logger = logging.getLogger(__name__)


class PaymentError(RuntimeError):
    pass


@dataclass
class QrIntent:
    provider: str
    provider_ref: str
    amount: Decimal
    currency: str
    expires_at: datetime | None
    raw: dict
    qr_payload: str | None = None


class CucuQrClient:
    """Cliente mínimo para https://docs.cucu.bo/payments/cobros-qr."""

    def __init__(self) -> None:
        if not settings.cucu_api_key:
            raise PaymentError(
                "CUCU_API_KEY no está configurado. Pide una API key de sandbox a "
                "CUCU o usa PAYMENT_PROVIDER=mock_qr."
            )
        self._client = httpx.AsyncClient(
            base_url=settings.cucu_base_url.rstrip("/") + "/",
            timeout=20.0,
            headers={"X-Api-Key": settings.cucu_api_key},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def create_qr(self, order: Order) -> QrIntent:
        idempotency_key = f"order-{order.id}"
        response = await self._client.post(
            "qr",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "amount": f"{Decimal(order.total):.2f}",
                "gloss": f"Pedido {order.number}",
                "expiration": settings.cucu_expiration,
                "externalReference": order.number,
                "metadata": {"channel": "whatsapp", "order": order.number},
            },
        )
        if response.status_code >= 400:
            raise PaymentError(
                f"CUCU QR {response.status_code}: {response.text[:500]}"
            )
        data = response.json()
        expires_at = None
        if data.get("expiresAt"):
            try:
                expires_at = datetime.fromisoformat(
                    str(data["expiresAt"]).replace("Z", "+00:00")
                )
            except ValueError:
                expires_at = None
        return QrIntent(
            provider="cucu_qr",
            provider_ref=str(data["qrId"]),
            amount=Decimal(str(data.get("amount", order.total))),
            currency=data.get("currency", "BOB"),
            expires_at=expires_at,
            raw=data,
        )

    async def status(self, qr_id: str) -> dict:
        response = await self._client.get(f"qr/{qr_id}")
        if response.status_code >= 400:
            raise PaymentError(
                f"CUCU QR status {response.status_code}: {response.text[:300]}"
            )
        return response.json()


async def create_payment(session: AsyncSession, order: Order) -> Payment:
    """Crea el pago pendiente y, si aplica, el QR en la pasarela."""
    if settings.payment_provider == "cucu_qr":
        client = CucuQrClient()
        try:
            intent = await client.create_qr(order)
        finally:
            await client.close()
        payment = Payment(
            order_id=order.id,
            provider=intent.provider,
            provider_ref=intent.provider_ref,
            amount=intent.amount,
            currency=intent.currency,
            status="pending",
            expires_at=intent.expires_at,
            raw=intent.raw,
        )
        session.add(payment)
        return payment

    provider_ref = f"mock-{uuid.uuid4().hex}"
    payment = Payment(
        order_id=order.id,
        provider="mock_qr",
        provider_ref=provider_ref,
        amount=order.total,
        currency=order.currency,
        status="pending",
        expires_at=utcnow() + timedelta(minutes=settings.payment_ttl_minutes),
    )
    payment.qr_payload = json.dumps(
        {
            "provider": "mock_qr",
            "ref": provider_ref,
            "order": order.number,
            "amount": str(order.total),
            "currency": order.currency,
        },
        ensure_ascii=False,
    )
    session.add(payment)
    return payment


def verify_standard_webhook(
    headers: dict[str, str], raw_body: bytes, secret: str, tolerance: int = 300
) -> bool:
    """Verifica la firma Standard Webhooks de CUCU.

    ``headers`` debe traer ``webhook-id``, ``webhook-timestamp`` y
    ``webhook-signature``. El secreto tiene el formato ``whsec_<base64>``.
    """
    message_id = headers.get("webhook-id")
    timestamp = headers.get("webhook-timestamp")
    signatures = headers.get("webhook-signature")
    if not message_id or not timestamp or not signatures or not secret:
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - timestamp_int) > tolerance:
        return False

    secret_value = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(secret_value)
    except Exception:  # noqa: BLE001
        return False
    signed = f"{message_id}.{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = base64.b64encode(
        hmac.new(key, signed, hashlib.sha256).digest()
    ).decode("ascii")

    candidates = []
    for part in signatures.split():
        if part.startswith("v1,"):
            candidates.append(part[3:])
    return any(hmac.compare_digest(expected, candidate) for candidate in candidates)


def new_event_id() -> str:
    return f"evt-{uuid.uuid4()}"
