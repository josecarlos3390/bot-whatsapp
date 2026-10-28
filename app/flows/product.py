"""Ficha de producto y preguntas por atributo.

Extraído de `agent.py` para que el archivo de enrutamiento no crezca.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact
from ..replies import AgentReply
from ..services import catalog, funnel
from ..whatsapp import Outbound
from .text import card_description


async def detail(
    agent,
    session: AsyncSession,
    contact: Contact,
    sku: str,
) -> AgentReply:
    """Ficha del producto: precio, especificaciones, acciones y complemento."""
    from ..agent import Toolbox

    agent._trace("Ficha de producto")
    toolbox = Toolbox(session, contact, agent.wa)
    result = await toolbox.tool_get_product(sku)
    if not result.get("ok"):
        return AgentReply(
            [
                Outbound(
                    text="No encontré ese producto. ¿Querés ver otra opción?"),
            ]
        )
    product = result["product"]
    await funnel.track(
        session, "product_view", contact=contact, sku=product.get("sku")
    )
    stock = sum((product.get("stock_by_store") or {}).values())
    base = Decimal(
        product.get("base_price") or product.get("final_price") or 0
    )
    final = Decimal(product.get("final_price") or base)
    discount = str(product.get("discount_percent") or "0")
    lines = [f"*{product['name']}*"]
    if product.get("brand"):
        lines.append(f"Marca: {product['brand']}")
    if product.get("is_promotion"):
        lines.extend(
            [
                f"Precio de lista: Bs {base:,.2f}",
                f"Precio con descuento: *Bs {final:,.2f}*",
                f"Descuento: {discount}%",
            ]
        )
    elif product.get("is_special_price"):
        lines.extend(
            [
                f"Precio de lista: Bs {base:,.2f}",
                f"Precio especial vigente: *Bs {final:,.2f}*",
            ]
        )
    else:
        lines.append(f"Precio: *Bs {final:,.2f}*")
    if product.get("period_to"):
        lines.append(f"Vigente hasta {product['period_to']}")
    # Disponibilidad concreta: el cliente pregunta "¿tenés stock?" y la
    # ficha repetía lo mismo sin responder.
    if stock > 0:
        unidades = "unidad" if stock == 1 else "unidades"
        lines.append(f"Disponible: {stock:,} {unidades}".replace(",", "."))
    else:
        lines.append("Sin stock por ahora")
    for tier in product.get("tiers") or []:
        if tier.get("quantity") and tier.get("price"):
            lines.append(
                f"Por {tier['quantity']} unidades: Bs {tier['price']} c/u"
            )
    attrs = product.get("attributes") or {}
    if product.get("category"):
        lines.append(f"Categoría: {product['category']}")
    if attrs.get("model"):
        lines.append(f"Modelo: {attrs['model']}")
    if attrs.get("weight_kg"):
        lines.append(f"Peso: {attrs['weight_kg']} kg")
    specs = attrs.get("specs") or {}
    if isinstance(specs, dict) and specs:
        preferred = (
            "Garantía",
            "Garantia",
            "Medidas",
            "Material",
            "Tamaño",
            "Tamano",
            "Potencia",
            "Capacidad",
            "Color",
        )
        ordered = [key for key in preferred if key in specs]
        ordered += [key for key in specs if key not in ordered]
        detail = " · ".join(
            f"{key}: {specs[key]}" for key in ordered[:4]
        )
        if detail:
            lines.append(detail[:260])
    description = agent._card_description(
        attrs.get("description") or "", limit=220
    )
    if description and description.upper() != (product.get("name") or "").upper():
        lines.append(f"Descripción: {description}")
    if product.get("barcode"):
        lines.append(f"Código de barra: {product['barcode']}")
    # Complemento con stock validado: sube el ticket sin inventar nada.
    combo = await catalog.complements(
        session, product["sku"], product["name"], limit=1
    )
    if combo:
        extra = combo[0]
        lines.append(
            f"Para completar: {extra.name.title()} — Bs {extra.price} "
            f"(escribí *agregar {extra.sku}*)"
        )
    # Lista de acciones: "Agregar 1/2/3" queda atado a ESTE producto,
    # sin los botones numerados que no decían a cuál correspondían.
    rows: list[dict] = []
    if stock > 0:
        for quantity in (1, 2, 3):
            rows.append(
                {
                    "id": f"add:{product['sku']}:{quantity}",
                    "title": f"Agregar {quantity}",
                    "description": "Al carrito",
                }
            )
    rows.append(
        {
            "id": "catalog",
            "title": "Ver otra opción",
            "description": "Volver a buscar",
        }
    )
    rows.append(
        {
            "id": "human",
            "title": "Hablar con asesor",
            "description": "Te atiende una persona",
        }
    )
    messages = []
    image_info = await catalog.primary_image_info(
        session, product["sku"]
    )
    image_url = image_info["url"] if image_info else None
    is_placeholder = bool(
        image_info and image_info.get("source") == "demo"
    )
    if not image_url and settings.product_image_placeholder:
        image_url = settings.product_image_placeholder
        is_placeholder = True
    if image_url:
        messages.append(
            Outbound(
                kind="image",
                url=image_url,
                text=(
                    "Imagen referencial"
                    if is_placeholder
                    else product["name"][:1024]
                ),
            )
        )
    messages.append(
        Outbound(
            kind="list",
            text="\n".join(lines),
            button_text="¿Qué hacemos?",
            sections=[{"title": "Acciones", "rows": rows}],
        )
    )
    return AgentReply(messages)



async def attribute(
    agent,
    session: AsyncSession,
    contact: Contact,
    sku: str,
    atributo: str,
) -> AgentReply | None:
    """Responde color, material, tipo o medida con los datos de VTEX."""
    from ..agent import Toolbox

    """Responde color/material/tipo con los datos de VTEX."""
    caja = Toolbox(session, contact, agent.wa)
    resultado = await caja.tool_get_product(sku)
    if not resultado.get("ok"):
        return None
    producto = resultado.get("product") or {}
    attributes = producto.get("attributes") or {}
    specs = attributes.get("specs") if isinstance(attributes, dict) else {}
    specs = specs if isinstance(specs, dict) else {}
    nombre = producto.get("name") or "ese producto"

    if atributo == "color":
        valor = attributes.get("color") or specs.get("Color")
        etiqueta = "color"
    elif atributo == "material":
        valor = attributes.get("material") or specs.get("Material")
        etiqueta = "material"
    elif atributo == "tipo":
        valor = attributes.get("product_type") or specs.get("Tipo")
        etiqueta = "tipo"
    else:
        valor = specs.get("Medidas") or specs.get("Tamaño") or attributes.get(
            "size"
        )
        etiqueta = "medida"
    if not valor:
        agent._trace(f"Atributo sin dato: {atributo}")
        return AgentReply(
            [
                Outbound(
                    kind="buttons",
                    text=(
                        f"No tengo el {etiqueta} de *{nombre}* cargado en "
                        "el catálogo. ¿Querés que te derive con un asesor "
                        "o ver otra opción?"
                    ),
                    buttons=[
                        {"id": "human", "title": "Asesor"},
                        {"id": "catalog", "title": "Ver categorías"},
                    ],
                )
            ]
        )
    agent._trace(f"Atributo: {etiqueta}")
    return AgentReply(
        [
            Outbound(
                text=(
                    f"*{nombre}*\n"
                    f"{etiqueta.capitalize()}: *{valor}*"
                )
            )
        ]
    )

