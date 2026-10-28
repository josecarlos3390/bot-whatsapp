"""Seguimiento por CI/NIT cuando el cliente no tiene el número de pedido."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact
from .order_tracking import _date, _money, format_order

logger = logging.getLogger(__name__)

# CI boliviana: 6 a 8 dígitos; NIT: 7 a 12. Se excluyen los IDs de pedido
# (más largos o con sufijo -01).
DOCUMENTO_RE = __import__("re").compile(r"(?<!\d)(\d{6,12})(?!\d)")

PEDIR_DOCUMENTO = (
    "No hace falta el número de pedido: pasame tu *CI o NIT* y busco tus "
    "compras a tu nombre."
)


def extract_documento(text: str) -> str | None:
    """Documento (CI/NIT) dentro del mensaje, si lo hay."""
    import re

    valor = (text or "").strip()
    if re.search(r"\d{13,}", valor):
        return None  # es un ID de pedido, no un documento
    match = DOCUMENTO_RE.search(valor)
    if not match:
        return None
    return match.group(1)


async def lookup_by_document(
    session: AsyncSession,
    contact: Contact,
    documento: str,
) -> dict:
    """Busca los pedidos del cliente por CI/NIT."""
    from ..sap import SapError, SapNotFound, get_sap

    documento = (documento or "").strip()
    if not contact.tax_id:
        contact.tax_id = documento[:20]
    try:
        sap = get_sap(session)
        pedidos = await sap.get_customer_purchases(documento, top=5, skip=0)
    except SapNotFound:
        pedidos = []
    except SapError:
        logger.exception("No se pudieron leer las compras por documento")
        return {
            "text": (
                "No pude consultar el sistema en este momento. "
                "Te derivo con un asesor para que lo revise."
            ),
            "finished": True,
            "needs_handoff": True,
        }
    except Exception:  # noqa: BLE001 - nunca dejar al cliente sin respuesta
        logger.exception("Error inesperado buscando compras por documento")
        return {
            "text": (
                "No pude consultar tus compras ahora. "
                "¿Querés que te pase con un asesor?"
            ),
            "finished": True,
            "needs_handoff": True,
        }

    if not pedidos:
        return {
            "text": (
                f"No encontré compras con el documento *{documento}*. "
                "Puede ser que la compra esté a nombre de otra persona o con "
                "otro documento.\n\n"
                "¿Querés que te derive con un asesor para revisarlo?"
            ),
            "finished": True,
            "needs_handoff": True,
        }

    if len(pedidos) == 1:
        return {
            "text": format_order(pedidos[0]),
            "finished": True,
            "needs_handoff": False,
        }

    lineas = [f"Encontré *{len(pedidos)} compras* a tu nombre:", ""]
    for pedido in pedidos[:5]:
        numero = pedido.get("orderId") or pedido.get("sequence") or "—"
        fecha = _date(pedido.get("creationDate") or pedido.get("authorizedDate"))
        total = _money(pedido.get("value") or pedido.get("totalValue") or 0)
        estado = str(pedido.get("status") or "").strip() or "—"
        lineas.append(f"• {numero} · {fecha} · Bs {total} · {estado}")
    lineas.append("")
    lineas.append("Decime cuál te interesa y te muestro el detalle.")
    return {
        "text": "\n".join(lineas),
        "finished": True,
        "needs_handoff": False,
    }
