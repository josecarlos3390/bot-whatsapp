"""¿Estamos listos para migrar a producción y usar el catálogo nativo?

Cada criterio se verifica solo, con evidencia. Los que no se pueden verificar
automáticamente quedan marcados como manuales.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Advisor, CatalogItem, ProductImage
from . import catalog_quality, knowledge

# Políticas que el carrito nativo necesita sí o sí.
POLITICAS = {
    "envios": "Envíos y entregas",
    "garantias": "Garantías",
    "pagos": "Medios de pago",
    "devoluciones": "Devoluciones y cambios",
}
PLACEHOLDERS = ("[verificar", "por definir", "pendiente", "xxx")


def _politica(articulo) -> dict:
    contenido = (articulo.content or "").lower()
    tiene_placeholder = any(marca in contenido for marca in PLACEHOLDERS)
    return {
        "ok": articulo.status == "published" and not tiene_placeholder,
        "detail": (
            "borrador con datos por completar"
            if tiene_placeholder and articulo.status == "published"
            else f"estado {articulo.status}"
            if articulo.status != "published"
            else "publicada"
        ),
    }


async def readiness(session: AsyncSession) -> dict:
    criterios: list[dict] = []

    informe = await catalog_quality.report(session, limit=3)

    criterios.append(
        {
            "key": "fotos",
            "label": "Productos con foto",
            "ok": informe["sin_foto"] == 0,
            "detail": f"{informe['sin_foto']} sin foto",
        }
    )
    criterios.append(
        {
            "key": "titulos",
            "label": "Títulos aptos para catálogo",
            "ok": informe["nombres_largos"] == 0,
            "detail": f"{informe['nombres_largos']} con más de 70 caracteres",
        }
    )
    criterios.append(
        {
            "key": "coherencia",
            "label": "Títulos coherentes",
            "ok": informe["nombres_cruzados"] == 0,
            "detail": f"{informe['nombres_cruzados']} con rubros mezclados",
        }
    )

    articulos = {a.source.rsplit("/", 1)[-1].replace(".md", ""): a for a in knowledge.load_articles()}
    faltantes = []
    for clave in POLITICAS:
        articulo = articulos.get(clave)
        if articulo is None:
            faltantes.append(f"{clave}: no existe")
            continue
        estado = _politica(articulo)
        if not estado["ok"]:
            faltantes.append(f"{clave}: {estado['detail']}")
    criterios.append(
        {
            "key": "politicas",
            "label": "Políticas publicadas",
            "ok": not faltantes,
            "detail": "; ".join(faltantes) if faltantes else "todas publicadas",
        }
    )

    total = int(
        await session.scalar(
            select(func.count())
            .select_from(CatalogItem)
            .where(CatalogItem.active.is_(True))
        )
        or 0
    )
    con_foto = int(
        await session.scalar(
            select(func.count(func.distinct(ProductImage.sku)))
            .select_from(ProductImage)
            .join(CatalogItem, CatalogItem.sku == ProductImage.sku)
            .where(CatalogItem.active.is_(True))
        )
        or 0
    )
    ratio = (con_foto / total * 100) if total else 0
    criterios.append(
        {
            "key": "feed",
            "label": "Feed aceptable por Meta",
            "ok": ratio >= 95,
            "detail": f"{ratio:.1f}% de productos con foto ({con_foto}/{total})",
        }
    )

    nativo = bool(
        settings.wa_native_catalog_enabled
        and settings.wa_catalog_id
        and settings.wa_commerce_account_id
    )
    criterios.append(
        {
            "key": "nativo",
            "label": "Catálogo nativo configurado",
            "ok": nativo,
            "detail": "activo"
            if nativo
            else "falta WA_CATALOG_ID / WA_COMMERCE_ACCOUNT_ID",
        }
    )

    guardia = int(
        await session.scalar(
            select(func.count())
            .select_from(Advisor)
            .where(Advisor.active.is_(True), Advisor.on_duty.is_(True))
        )
        or 0
    )
    criterios.append(
        {
            "key": "guardia",
            "label": "Asesor de guardia",
            "ok": guardia > 0,
            "detail": f"{guardia} de guardia",
        }
    )

    criterios.append(
        {
            "key": "presupuesto",
            "label": "Presupuesto de mensajería",
            "ok": False,
            "manual": True,
            "detail": "confirmar con administración",
        }
    )

    listos = [c for c in criterios if c["ok"]]
    return {
        "ready": len(listos) == len(criterios),
        "score": f"{len(listos)}/{len(criterios)}",
        "blocking": [c for c in criterios if not c["ok"]],
        "criteria": criterios,
    }
