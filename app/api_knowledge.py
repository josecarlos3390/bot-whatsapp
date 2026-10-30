"""Editor de la base de conocimiento desde la consola.

Los artículos son archivos `.md` en `knowledge/`. Desde acá se listan, se
editan y se crean, con validación previa para no romper el formato.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session


async def _admin(
    request: Request,
    x_admin_token: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Misma protección que el resto de la administración."""
    from .api import require_advisor

    advisor = await require_advisor(request, x_admin_token, session)
    if not advisor.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requiere administrador")
    return advisor


router = APIRouter(tags=["knowledge"], dependencies=[Depends(_admin)])

CARPETA = Path("knowledge")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,59}$")
ESTADOS = {"published", "draft", "archived"}


class KnowledgePayload(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    status: str = "draft"
    tags: str = ""
    content: str = Field(min_length=1, max_length=20000)


def _ruta(slug: str) -> Path:
    if not SLUG.match(slug or ""):
        raise HTTPException(status_code=400, detail="Nombre inválido")
    ruta = (CARPETA / f"{slug}.md").resolve()
    # En Windows el nombre de la carpeta puede diferir en mayúsculas.
    base = str(CARPETA.resolve()).lower()
    if not str(ruta).lower().startswith(base):
        raise HTTPException(status_code=400, detail="Ruta inválida")
    return ruta


def _leer(slug: str) -> dict:
    ruta = _ruta(slug)
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="No existe el artículo")
    texto = ruta.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    cuerpo = texto
    if texto.startswith("---"):
        partes = texto.split("---", 2)
        if len(partes) == 3:
            for linea in partes[1].splitlines():
                if ":" in linea:
                    clave, valor = linea.split(":", 1)
                    meta[clave.strip().lower()] = valor.strip()
            cuerpo = partes[2].lstrip("\n")
    return {
        "slug": slug,
        "title": meta.get("title") or slug.replace("-", " ").title(),
        "status": (meta.get("status") or "draft").lower(),
        "tags": meta.get("tags") or "",
        "content": cuerpo.strip(),
        "actualizado": datetime.fromtimestamp(
            ruta.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def _escribir(slug: str, datos: KnowledgePayload) -> dict:
    estado = (datos.status or "draft").strip().lower()
    if estado not in ESTADOS:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Usá: {', '.join(sorted(ESTADOS))}",
        )
    ruta = _ruta(slug)
    etiquetas = ", ".join(
        etiqueta.strip()
        for etiqueta in (datos.tags or "").split(",")
        if etiqueta.strip()
    )
    if estado == "published" and not etiquetas:
        raise HTTPException(
            status_code=400,
            detail="Un artículo publicado necesita al menos una etiqueta",
        )
    if estado == "published" and len(datos.content.strip()) < 40:
        raise HTTPException(
            status_code=400,
            detail="Un artículo publicado necesita contenido (mínimo 40)",
        )
    CARPETA.mkdir(exist_ok=True)
    texto = (
        "---\n"
        f"title: {datos.title.strip()}\n"
        f"status: {estado}\n"
        f"tags: {etiquetas}\n"
        "---\n\n"
        f"{datos.content.strip()}\n"
    )
    ruta.write_text(texto, encoding="utf-8")
    return _leer(slug)


@router.get("/admin/knowledge-base")
async def knowledge_list() -> dict:
    """Artículos de la base con su estado."""
    articulos = []
    if CARPETA.exists():
        for archivo in sorted(CARPETA.glob("*.md")):
            if archivo.name.lower().startswith("readme"):
                continue
            try:
                articulos.append(_leer(archivo.stem))
            except HTTPException:
                continue
    return {"articulos": articulos, "total": len(articulos)}


@router.get("/admin/knowledge-base/{slug}")
async def knowledge_get(slug: str) -> dict:
    return _leer(slug)


@router.post("/admin/knowledge-base")
async def knowledge_create(payload: KnowledgePayload) -> dict:
    """Crea un artículo nuevo a partir del título."""
    import unicodedata

    base = unicodedata.normalize("NFKD", payload.title.lower())
    simple = "".join(c for c in base if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", simple).strip("-")[:60]
    if not slug:
        raise HTTPException(status_code=400, detail="Título inválido")
    ruta = _ruta(slug)
    if ruta.exists():
        raise HTTPException(
            status_code=400, detail="Ya existe un artículo con ese título"
        )
    return _escribir(slug, payload)


@router.put("/admin/knowledge-base/{slug}")
async def knowledge_save(slug: str, payload: KnowledgePayload) -> dict:
    return _escribir(slug, payload)


@router.delete("/admin/knowledge-base/{slug}")
async def knowledge_delete(slug: str) -> dict:
    """No borra: lo archiva renombrando el archivo."""
    ruta = _ruta(slug)
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="No existe el artículo")
    destino = ruta.with_suffix(".md.archivado")
    if destino.exists():
        destino.unlink()
    ruta.rename(destino)
    return {"ok": True, "archivado": destino.name}


@router.post("/admin/knowledge-base/validar")
async def knowledge_validate() -> dict:
    """Revisa todos los artículos antes de publicar."""
    from scripts.validar_conocimiento import validar

    problemas, advertencias = validar(CARPETA)
    return {
        "problemas": problemas,
        "advertencias": advertencias,
        "ok": not problemas,
    }
