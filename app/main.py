from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import router
from .config import settings
from .db import SessionLocal, engine, init_db
from .runtime import whatsapp
from .sap import close_live_reader, warmup_live_reader
from .seed import seed_demo
from .services.sap_consumer import sap_event_consumer
from .services.occasion_store import seed_examples as seed_occasions
from .services import handoffs

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _warm_sap() -> None:
    try:
        await warmup_live_reader()
        logger.info("Sesión SAP precalentada")
    except Exception:  # noqa: BLE001 - no tumbar la app
        logger.exception("No se pudo precalentar la sesión SAP")



async def _assign_queue() -> None:
    """Reparte cada minuto los casos en cola si hay asesores disponibles."""
    from .services import presence

    while True:
        try:
            await asyncio.sleep(60)
            async with SessionLocal() as session:
                asignados = await presence.assign_queued(session)
            if asignados:
                logger.info("Casos asignados desde la cola: %s", asignados)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - el reparto no debe matar la app
            logger.exception("Error asignando la cola de casos")

async def _sweep_handoffs() -> None:
    """Cierra los casos que nadie atendió, aunque el cliente no escriba.

    Sin este barrido, un handoff pendiente queda en la cola para siempre y
    ensucia el SLA (el aviso al cliente se hace cuando vuelve a escribir).
    """
    interval = max(settings.handoff_sweep_seconds, 60)
    while True:
        try:
            await asyncio.sleep(interval)
            async with SessionLocal() as session:
                result = await handoffs.sweep_stale_handoffs(
                    session,
                    pending_minutes=settings.handoff_auto_resume_minutes,
                    taken_minutes=settings.handoff_taken_timeout_minutes,
                )
            if result.get("resolved"):
                logger.info(
                    "Barrido de handoffs: %s cerrados", result["resolved"]
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - el barrido no debe matar la app
            logger.exception("Error en el barrido de handoffs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if settings.seed_demo:
        async with SessionLocal() as session:
            added = await seed_demo(session)
        if added:
            logger.info("Catálogo demo cargado: %s productos", added)
    async with SessionLocal() as session:
        added_occasions = await seed_occasions(session)
    if added_occasions:
        logger.info("Ocasiones de ejemplo cargadas: %s", added_occasions)
    if settings.sap_mode == "service_layer" and settings.sap_live_reads:
        # En segundo plano: el login de SAP no debe retrasar el arranque HTTP.
        app.state.sap_warmup = asyncio.create_task(_warm_sap())
    await sap_event_consumer.start()
    app.state.handoff_sweeper = asyncio.create_task(_sweep_handoffs())
    app.state.queue_assigner = asyncio.create_task(_assign_queue())
    logger.info("Servicio listo (SAP_MODE=%s, WA_DRY_RUN=%s)", settings.sap_mode, settings.wa_dry_run)
    yield
    await sap_event_consumer.stop()
    sweeper = getattr(app.state, "handoff_sweeper", None)
    if sweeper is not None and not sweeper.done():
        sweeper.cancel()
    queue_task = getattr(app.state, "queue_assigner", None)
    if queue_task is not None and not queue_task.done():
        queue_task.cancel()
    task = getattr(app.state, "sap_warmup", None)
    if task is not None and not task.done():
        task.cancel()
    await whatsapp.close()
    await close_live_reader()
    await engine.dispose()


app = FastAPI(
    title="Chatbot WhatsApp + SAP Business One",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(router)
_admin_dist = Path(__file__).resolve().parent.parent / "admin-web" / "dist"


class _SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


if _admin_dist.exists():
    app.mount(
        "/console",
        _SpaStaticFiles(directory=_admin_dist, html=True),
        name="console",
    )
