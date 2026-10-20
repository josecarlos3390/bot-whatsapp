"""RabbitMQ consumer for SAP events published by integration-paas."""

from __future__ import annotations

import asyncio
import json
import logging

import aio_pika

from ..config import settings
from ..db import SessionLocal
from .sap_events import process_sap_event

logger = logging.getLogger(__name__)


class SapEventConsumer:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if not settings.sap_event_queue_enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="sap-event-consumer")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                connection = await aio_pika.connect_robust(
                    settings.rabbitmq_url
                )
                async with connection:
                    channel = await connection.channel()
                    await channel.set_qos(
                        prefetch_count=settings.sap_event_prefetch
                    )
                    exchange = await channel.declare_exchange(
                        settings.sap_event_exchange,
                        aio_pika.ExchangeType.TOPIC,
                        durable=True,
                    )
                    dlx = await channel.declare_exchange(
                        settings.sap_event_dlx,
                        aio_pika.ExchangeType.FANOUT,
                        durable=True,
                    )
                    dlq = await channel.declare_queue(
                        settings.sap_event_dlq, durable=True
                    )
                    await dlq.bind(dlx)
                    queue = await channel.declare_queue(
                        settings.sap_event_queue,
                        durable=True,
                        arguments={
                            "x-dead-letter-exchange": settings.sap_event_dlx,
                            "x-dead-letter-routing-key": "failed",
                        },
                    )
                    await queue.bind(exchange, routing_key="#")
                    # Replace the old catch-all binding with the object types
                    # this consumer actually needs.
                    try:
                        await queue.unbind(exchange, routing_key="#")
                    except Exception:  # noqa: BLE001 - binding may not exist
                        pass
                    for object_type in ("4", "7", "13"):
                        await queue.bind(
                            exchange,
                            routing_key=(
                                f"{settings.sap_event_tenant}.{object_type}.*"
                            ),
                        )
                    logger.info(
                        "Consumiendo eventos SAP de %s",
                        settings.sap_event_queue,
                    )
                    async with queue.iterator() as iterator:
                        async for message in iterator:
                            if self._stopping:
                                break
                            await self._handle(message)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reintentar conexión
                if self._stopping:
                    break
                logger.exception("Consumer SAP sin conexión; reintento en 10s")
                await asyncio.sleep(10)

    async def _handle(self, message: aio_pika.IncomingMessage) -> None:
        try:
            payload = json.loads(message.body or b"{}")
            async with SessionLocal() as session:
                result = await process_sap_event(session, payload)
            logger.info("Evento SAP procesado: %s", result)
            await message.ack()
        except Exception:  # noqa: BLE001 - a DLQ
            logger.exception("Evento SAP falló; enviando a DLQ")
            await message.reject(requeue=False)


sap_event_consumer = SapEventConsumer()
