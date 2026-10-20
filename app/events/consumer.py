"""RabbitMQ consumer for SAP outbox events.

Run as a separate process:
    python -m app.events.consumer
"""

from __future__ import annotations

import asyncio
import json
import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from ..config import settings
from ..db import SessionLocal
from ..services.sap_events import process_sap_event

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


async def _handle_message(
    message: aio_pika.IncomingMessage,
    exchange: aio_pika.Exchange,
) -> None:
    try:
        payload = json.loads(message.body or b"{}")
    except json.JSONDecodeError:
        logger.exception("Evento SAP con JSON inválido; se envía a DLQ")
        await message.reject(requeue=False)
        return

    try:
        async with SessionLocal() as session:
            result = await process_sap_event(session, payload)
        logger.info(
            "Evento SAP %s -> %s",
            result.get("event_id"),
            result.get("status"),
        )
        await message.ack()
    except Exception:  # noqa: BLE001 - reintentar o DLQ
        retries = int((message.headers or {}).get("x-retry", 0))
        if retries < MAX_RETRIES:
            headers = dict(message.headers or {})
            headers["x-retry"] = retries + 1
            logger.warning(
                "Reintentando evento SAP (%s/%s)", retries + 1, MAX_RETRIES
            )
            await exchange.publish(
                Message(
                    body=message.body,
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    headers=headers,
                ),
                routing_key=message.routing_key or "sap.event",
            )
            await message.ack()
        else:
            logger.exception("Evento SAP agotó reintentos; se envía a DLQ")
            await message.reject(requeue=False)


async def run() -> None:
    if not settings.sap_event_queue_enabled:
        raise SystemExit("SAP_EVENT_QUEUE_ENABLED=false")

    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.sap_event_prefetch)

        dlx = await channel.declare_exchange(
            settings.sap_event_dlx,
            ExchangeType.FANOUT,
            durable=True,
        )
        dlq = await channel.declare_queue(
            settings.sap_event_dlq, durable=True
        )
        await dlq.bind(dlx)

        exchange = await channel.declare_exchange(
            settings.sap_event_exchange,
            ExchangeType.TOPIC,
            durable=True,
        )
        queue = await channel.declare_queue(
            settings.sap_event_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.sap_event_dlx,
                "x-dead-letter-routing-key": "failed",
            },
        )
        # Only this tenant's events (routing key {schema}.{objectType}.{eventType}).
        await queue.bind(
            exchange, routing_key=f"{settings.sap_event_tenant}.#"
        )
        logger.info(
            "Consumiendo %s desde %s",
            settings.sap_event_queue,
            settings.sap_event_exchange,
        )
        await queue.consume(
            lambda message: _handle_message(message, exchange)
        )
        await asyncio.Future()


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
