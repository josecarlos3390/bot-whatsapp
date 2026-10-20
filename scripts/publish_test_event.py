"""Publica un evento SAP de prueba en RabbitMQ (para probar el consumidor)."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from app.config import settings


async def run(args) -> None:
    event_id = args.event_id or str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "tenant_id": args.tenant_id,
        "event_type": args.event_type,
        "object_type": args.object_type,
        "aggregate_id": args.aggregate_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": None,
    }
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            settings.sap_event_exchange,
            ExchangeType.TOPIC,
            durable=True,
        )
        await exchange.publish(
            Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
            ),
            routing_key=f"{args.object_type}.{args.event_type}",
        )
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id")
    parser.add_argument("--tenant-id", default=settings.sap_event_tenant)
    parser.add_argument("--event-type", default="Created")
    parser.add_argument("--object-type", required=True)
    parser.add_argument("--aggregate-id", required=True)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
