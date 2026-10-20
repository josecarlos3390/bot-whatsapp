from __future__ import annotations

import logging

from arq import cron
from arq.connections import RedisSettings

from .config import settings
from .db import SessionLocal, engine, init_db
from .runtime import whatsapp
from .sap import close_live_reader, warmup_live_reader
from .seed import seed_demo
from .services.ingest import ingest_inbound

logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def startup(ctx):
    await init_db()
    if settings.seed_demo:
        async with SessionLocal() as session:
            await seed_demo(session)
    if settings.sap_mode == "service_layer" and settings.sap_live_reads:
        try:
            await warmup_live_reader()
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo precalentar SAP en el worker")
    logger.info("Worker listo")


async def shutdown(ctx):
    await whatsapp.close()
    await close_live_reader()
    await engine.dispose()


async def process_inbound(
    ctx,
    wa_id: str,
    text: str,
    wa_message_id: str,
    name: str | None = None,
    order: dict | None = None,
    media: dict | None = None,
):
    async with SessionLocal() as session:
        await ingest_inbound(
            session,
            wa_id=wa_id,
            text=text,
            wa_message_id=wa_message_id,
            name=name,
            order=order,
            media=media,
        )


async def job_sync_promotions(ctx):
    if settings.sap_mode != "service_layer":
        return
    from scripts.sync_promotions import sync as sync_promotions

    await sync_promotions()


async def job_sync_catalog(ctx):
    if settings.sap_mode != "service_layer":
        return
    from scripts.sync_catalog import sync as sync_catalog

    await sync_catalog()


async def summarize_conversation_job(ctx, conversation_id: str):
    from .services.memory import summarize_conversation

    await summarize_conversation(conversation_id)


async def job_sync_purchases(ctx):
    if settings.sap_mode != "service_layer":
        return
    from scripts.sync_purchases import run as sync_purchases

    await sync_purchases(None, None, None)


async def job_send_feedback_surveys(ctx):
    from .services.feedback_outbound import send_due_surveys

    async with SessionLocal() as session:
        await send_due_surveys(session, whatsapp)


class WorkerSettings:
    functions = [process_inbound, summarize_conversation_job]
    cron_jobs = [
        # Promociones cada 6 horas; catálogo e historial de madrugada.
        cron(job_sync_promotions, hour={0, 6, 12, 18}, minute=10),
        cron(job_sync_catalog, hour=3, minute=20),
        cron(job_sync_purchases, hour=4, minute=10),
        cron(job_send_feedback_surveys, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 3600
    max_tries = 3
