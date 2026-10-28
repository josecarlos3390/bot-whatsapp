"""Imágenes: interpretación y oferta de productos parecidos.

Extraído de `agent.py` para que el enrutamiento no crezca.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact
from ..replies import AgentReply
from ..services import ideas, media as media_service, vision
from ..whatsapp import Outbound


async def reply(
    agent,
    session: AsyncSession,
    contact: Contact,
    media: dict,
    texto: str = "",
) -> AgentReply | None:
    """Interpreta la imagen y ofrece productos parecidos del catálogo."""
    from ..agent import Toolbox, _caption_intencion, _caption_util, _frase_imagen

    """Interpreta la imagen y ofrece productos parecidos del catálogo."""
    contenido = await media_service.download(media.get("media_id") or "")
    if contenido is None:
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Recibí tu imagen pero no pude abrirla. ¿Me contás "
                        "qué producto es y qué querés saber?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver productos"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )
    archivo, mime = contenido
    descripcion = await vision.describe(archivo, mime)
    if descripcion is None:
        agent._trace("Imagen sin visión configurada")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Recibí tu imagen. Para buscarte algo igual o "
                        "parecido necesito que me digas qué producto es "
                        "(por ejemplo: taladro, licuadora, colchón).\n\n"
                        "¿Me lo escribís y te muestro opciones?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    objeto = descripcion.get("objeto") or ""
    categoria = descripcion.get("categoria") or ""
    marca = descripcion.get("marca") or ""
    atributos = descripcion.get("atributos") or ""
    if not objeto:
        agent._trace("Imagen sin producto reconocible")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        "Miré la imagen pero no reconozco un producto en "
                        "ella. ¿Me contás qué estás buscando?"
                    ),
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                )
            ]
        )

    # Lo que el cliente escribió junto a la foto ("quiero comprar algo
    # así") aporta intención y, si nombra un producto, manda la búsqueda.
    acompanante = _caption_util(texto)
    intencion = _caption_intencion(texto)
    consulta = " ".join(
        parte
        for parte in (acompanante, objeto, marca, atributos)
        if parte
    )
    caja = Toolbox(session, contact, agent.wa)
    resultado = await caja.tool_search_products(
        query=consulta, limit=8, ignore_state=True
    )
    productos = agent._ordenar_por_imagen(
        resultado.get("products") or [], descripcion
    )[:3]
    if productos:
        agent._trace(f"Imagen: {objeto} con opciones")
        lead = (
            _frase_imagen(acompanante, objeto, marca, intencion)
            + " En la tienda tenemos opciones parecidas:"
        )
        return AgentReply(
            [
                Outbound(text=lead),
                *agent._search_cards(productos[:3]),
                Outbound(
                    kind="buttons",
                    text="¿Te muestro el detalle de alguno o buscamos otra cosa?",
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                ),
            ]
        )

    # Sin coincidencia: se prueba por el rubro que detectó la visión.
    if categoria:
        rubro = await caja.tool_search_products(
            query=categoria, limit=6, ignore_state=True
        )
        productos = agent._ordenar_por_imagen(
            rubro.get("products") or [], descripcion
        )[:3]
    if productos:
        agent._trace(f"Imagen: {objeto} sin igual, rubro {categoria}")
        return AgentReply(
            [
                Outbound(
                    text=(
                        _frase_imagen(acompanante, objeto, marca, intencion)
                        + f" No tengo ese modelo exacto, pero en "
                        f"*{categoria or objeto}* tengo esto:"
                    )
                ),
                *agent._search_cards(productos[:3]),
                Outbound(
                    kind="buttons",
                    text="¿Te interesa alguna o hablamos con un asesor?",
                    buttons=[
                        {"id": "catalog", "title": "Ver categorías"},
                        {"id": "human", "title": "Asesor"},
                    ],
                ),
            ]
        )

    agent._trace(f"Imagen: {objeto} sin coincidencias")
    return AgentReply(
        [
            Outbound(
                kind="buttons",
                text=(
                    _frase_imagen(acompanante, objeto, marca, intencion)
                    + " No encontré algo igual en el catálogo ahora. "
                    "¿Querés que lo busque un asesor o te muestro otras "
                    "categorías?"
                ),
                buttons=[
                    {"id": "human", "title": "Asesor"},
                    {"id": "catalog", "title": "Ver categorías"},
                ],
            )
        ]
    )

