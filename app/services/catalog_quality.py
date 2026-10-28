"""Calidad del catálogo: lo que hace que el bot responda raro.

No es un problema de IA: un nombre mezclado, una categoría mal puesta o un
producto sin foto llegan al cliente como una respuesta extraña. Este informe
lista esos defectos con ejemplos concretos para que ecommerce los corrija.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogItem, ProductImage
from . import learning

# Palabras que no deberían convivir en un mismo título.
RUBROS = (
    "taladro", "amoladora", "sierra", "licuadora", "batidora", "heladera",
    "lavadora", "colchon", "televisor", "espejo", "sofa", "sillon",
    "alfombra", "cortina", "ventilador", "microondas", "horno", "broca",
    "disco", "repuesto",
)
# "ventilador de mesa" no es un título cruzado: el segundo rubro va
# introducido por una preposición.
_CONECTOR = re.compile(r"\b(de|para|con|sin|en)\s+$")
MAX_NOMBRE = 70



_MAYUSCULAS = re.compile(r"[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9\s/.,-]{14,}")


def _partes_titulo(nombre: str) -> tuple[str, str] | None:
    """Separa el título comercial del técnico (que va en mayúsculas)."""
    texto = (nombre or "").strip()
    if len(texto) < 40:
        return None
    match = _MAYUSCULAS.search(texto)
    if match is None or match.start() < 10:
        return None
    return texto[: match.start()].strip(), match.group(0).strip()


def _primer_rubro(texto: str) -> str | None:
    """Primer rubro mencionado en un texto ("taladro", "broca"...)."""
    bajo = (texto or "").lower()
    for match in re.finditer(r"[a-záéíóúñ]{4,}", bajo):
        palabra = match.group(0)
        for rubro in RUBROS:
            if palabra.rstrip("s") == rubro:
                return rubro
    return None


def _comparten_palabra(comercial: str, tecnica: str) -> bool:
    """Coherente si ambas mitades hablan del mismo rubro."""
    uno = _primer_rubro(comercial)
    otro = _primer_rubro(tecnica)
    if uno and otro:
        return uno == otro
    return True


async def report(session: AsyncSession, limit: int = 6) -> dict:
    activos = (
        await session.scalars(
            select(CatalogItem).where(CatalogItem.active.is_(True))
        )
    ).all()
    total = len(activos)

    con_imagen = {
        sku
        for sku in (
            await session.scalars(select(ProductImage.sku).distinct())
        ).all()
    }

    sin_foto = [item for item in activos if item.sku not in con_imagen]

    nombres_largos = [
        item for item in activos if len(item.name or "") > MAX_NOMBRE
    ]

    # Título incoherente: la parte comercial y la técnica no comparten
    # ninguna palabra ("Taladro ... BROCA PARA SIERRA COPA").
    nombres_cruzados = []
    for item in activos:
        partes = _partes_titulo(item.name or "")
        if partes is None:
            continue
        comercial, tecnica = partes
        if not _comparten_palabra(comercial, tecnica):
            nombres_cruzados.append(item)

    por_nombre = Counter((item.name or "").strip().lower() for item in activos)
    duplicados = [nombre for nombre, veces in por_nombre.items() if veces > 1]

    por_categoria = Counter((item.category or "").strip() for item in activos)
    categorias_chicas = [
        {"category": categoria, "count": veces}
        for categoria, veces in por_categoria.items()
        if categoria and veces < 3
    ][:limit]

    sin_precio = [item for item in activos if not item.price or item.price <= 0]

    # Avance del enriquecimiento con VTEX (keywords y especificaciones).
    enriquecidos = sum(
        1
        for item in activos
        if isinstance(item.attributes, dict)
        and item.attributes.get("keywords_source") == "vtex"
    )

    aprendidas = await learning.summary(session, limit=limit)

    def muestra(items: list) -> list[dict]:
        return [
            {"sku": item.sku, "name": item.name, "category": item.category}
            for item in items[:limit]
        ]

    return {
        "total": total,
        "sin_foto": len(sin_foto),
        "sin_foto_muestra": muestra(sin_foto),
        "nombres_largos": len(nombres_largos),
        "nombres_largos_muestra": muestra(nombres_largos),
        "nombres_cruzados": len(nombres_cruzados),
        "nombres_cruzados_muestra": muestra(nombres_cruzados),
        "duplicados": len(duplicados),
        "duplicados_muestra": duplicados[:limit],
        "sin_precio": len(sin_precio),
        "enriquecidos": enriquecidos,
        "enriquecidos_pct": round(enriquecidos / total * 100, 1) if total else 0,
        "sin_precio_muestra": muestra(sin_precio),
        "categorias_chicas": categorias_chicas,
        "busquedas_pendientes": aprendidas.get("top_pendientes", []),
        "buscadas_sin_resultado": sum(
            item.get("misses", 0) for item in aprendidas.get("top_pendientes", [])
        ),
    }
