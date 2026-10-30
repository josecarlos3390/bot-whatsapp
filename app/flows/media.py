"""Imágenes: interpretación y oferta de productos parecidos.

Extraído de `agent.py` para que el enrutamiento no crezca.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact
from ..replies import AgentReply
from ..services import ideas, media as media_service, vision
from ..whatsapp import Outbound


def _tokens(texto: str) -> set[str]:
    import re

    palabras = re.findall(r"[a-záéíóúñ0-9]{4,}", (texto or "").lower())
    return {p for p in palabras if p not in {"para", "con", "sin", "como"}}


def _coincide(descripcion, producto) -> bool:
    """¿El producto se parece de verdad o solo comparte el sustantivo?

    «Mochila pulverizadora» no es una mochila de colegio aunque comparta la
    palabra mochila: si la foto describe atributos y el producto no coincide
    con ninguno, no se ofrece como parecido.
    """
    objeto = str(descripcion.get("objeto") or "")
    atributos = str(descripcion.get("atributos") or "")
    buscados = _tokens(objeto) | _tokens(atributos)
    if not buscados:
        return True
    nombre = (producto.get("name") or "") + " " + str(
        producto.get("category") or ""
    )
    encontrados = _tokens(nombre)
    compartidos = buscados & encontrados
    if len(buscados) == 1:
        return bool(compartidos)
    # Con atributos en la foto hay que coincidir en algo más que el sustantivo.
    return len(compartidos) >= 2


async def _con_descuento(
    session, categoria: str, excluir: set[str], limite: int = 2
) -> list[dict]:
    """Alternativas del mismo rubro con mejor descuento vigente."""
    from ..services import catalog, rule_apply

    if not categoria:
        return []
    filas = await catalog.search_items(session, categoria, limit=12)
    if not filas:
        return []
    promos = await rule_apply.descuentos(session, [f.sku for f in filas])
    candidatos = [
        fila
        for fila in filas
        if fila.sku not in excluir and promos.get(fila.sku, 0) >= 15
    ]
    candidatos.sort(key=lambda fila: promos.get(fila.sku, 0), reverse=True)
    return [
        {
            "sku": fila.sku,
            "name": fila.name,
            "price": str(fila.price),
            "brand": fila.brand,
            "category": fila.category,
            "promo_discount_percent": str(promos.get(fila.sku, 0)),
        }
        for fila in candidatos[:limite]
    ]


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
    )
    # Solo los que se parecen de verdad: compartir el sustantivo no alcanza.
    productos = [p for p in productos if _coincide(descripcion, p)][:3]
    if productos:
        agent._trace(f"Imagen: {objeto} con opciones")
        # Alternativas del rubro con mejor descuento: el cliente ve lo que
        # se parece y también lo que conviene.
        vistos = {p.get("sku") for p in productos if p.get("sku")}
        alternativas = await _con_descuento(
            session, categoria or objeto, vistos, limite=2
        )
        lead = (
            _frase_imagen(acompanante, objeto, marca, intencion)
            + " En la tienda tenemos opciones parecidas:"
        )
        if alternativas:
            lead += (
                "\n\nY si buscás mejor precio, estas tienen descuento:"
            )
        return AgentReply(
            [
                Outbound(text=lead),
                # La lista ya cierra con su propio menú: no se pregunta
                # otra vez antes de que el cliente elija.
                *agent._search_cards(productos[:3] + alternativas),
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
            ]
        )

    # Sin nada parecido: se ofrece un puente a lo relacionado, como con los
    # productos que no existen por texto (una impresora → oficina/tecnología).
    if settings.deepseek_api_key:
        from ..services import related

        try:
            puente = await related.reply(
                agent, session, contact, objeto or categoria or ""
            )
        except Exception:  # noqa: BLE001 - nunca dejar sin respuesta
            puente = None
        if puente is not None:
            agent._trace(f"Imagen: {objeto} con puente a lo relacionado")
            return AgentReply(
                [
                    Outbound(
                        text=_frase_imagen(
                            acompanante, objeto, marca, intencion
                        )
                    ),
                    *puente.messages,
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

