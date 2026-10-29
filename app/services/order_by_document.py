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

KIND_LABELS = {
    "carnet": "carnet",
    "nit": "NIT",
    "telefono": "teléfono",
}


def pregunta_tipo(numero: str) -> dict:
    """Pregunta con qué dato buscar cuando el número es ambiguo."""
    return {
        "text": (
            f"El número *{numero}* puede ser tu carnet, tu NIT o tu "
            "teléfono. ¿Cuál de los tres es? Así busco con el criterio "
            "correcto."
        ),
        "buttons": [
            {"id": "doc:carnet", "title": "Carnet"},
            {"id": "doc:nit", "title": "NIT"},
            {"id": "doc:telefono", "title": "Teléfono"},
        ],
        "finished": False,
        "needs_handoff": False,
    }


def tipo_del_texto(text: str) -> str | None:
    """Qué tipo de número nombró el cliente, si lo dijo."""
    import re

    valor = (text or "").lower()
    if re.search(r"\b(carnet|cedula|cédula|ci)\b", valor):
        return "carnet"
    if re.search(r"\bnit\b", valor):
        return "nit"
    if re.search(r"\b(tel[eé]fono|celular|cel|whatsapp)\b", valor):
        return "telefono"
    return None


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
    kind: str = "carnet",
) -> dict:
    """Busca los pedidos del cliente por carnet, NIT o teléfono."""
    from ..sap import SapError, SapNotFound, get_sap

    documento = (documento or "").strip()
    if kind in {"carnet", "nit"} and not contact.tax_id:
        contact.tax_id = documento[:20]
    try:
        sap = get_sap(session)
        pedidos = await sap.get_customer_purchases(documento, top=5, skip=0)
        if not pedidos and kind == "telefono":
            # El teléfono no siempre resuelve directo: se busca el cliente y
            # después sus compras por documento.
            cliente = await sap.get_customer(documento)
            documento_cliente = str((cliente or {}).get("document") or "")
            if documento_cliente:
                pedidos = await sap.get_customer_purchases(
                    documento_cliente, top=5, skip=0
                )
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
                f"No encontré compras con ese {KIND_LABELS.get(kind, 'dato')} "
                f"(*{documento}*). Puede ser que la compra esté a nombre de "
                "otra persona o con otro dato.\n\n"
                "¿Querés que te derive con un asesor para revisarlo?"
            ),
            "finished": True,
            "needs_handoff": True,
        }

    if len(pedidos) == 1:
        # La lista de compras no trae el detalle completo: se pide el pedido
        # para mostrar total, artículos y entrega.
        completo = pedidos[0]
        numero = str(completo.get("orderId") or "")
        if numero:
            try:
                from ..sap import get_sap as _get_sap

                detalle = await _get_sap(session).get_order(numero)
                if detalle:
                    completo = detalle
            except Exception:  # noqa: BLE001 - se muestra lo que haya
                logger.debug("No se pudo ampliar el pedido", exc_info=True)
        return {
            "text": format_order(completo),
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


def variantes_telefono(phone: str) -> list[str]:
    """Formas en que el sistema puede tener guardado un teléfono."""
    import re

    digitos = re.sub(r"\D", "", phone or "")
    if len(digitos) < 7:
        return []
    variantes = [digitos]
    # Sin código de país (591 para Bolivia).
    if digitos.startswith("591") and len(digitos) > 8:
        variantes.append(digitos[3:])
    # Con 0 inicial, como se escribe localmente.
    variantes.append("0" + variantes[-1])
    return list(dict.fromkeys(v for v in variantes if v))


async def lookup_by_phone(
    session: AsyncSession,
    contact: Contact,
) -> dict | None:
    """Intenta encontrar los pedidos con el teléfono de la conversación.

    Devuelve None si el sistema no resuelve por teléfono (el integrador
    todavía no lo soporta) para que el flujo siga pidiendo CI/NIT.
    """
    from ..sap import SapError, get_sap

    telefono = getattr(contact, "phone_e164", None) or ""
    for variante in variantes_telefono(telefono):
        try:
            sap = get_sap(session)
            pedidos = await sap.get_customer_purchases(
                variante, top=5, skip=0
            )
        except SapError:
            return None
        except Exception:  # noqa: BLE001 - no romper el seguimiento
            logger.debug("Fallo la búsqueda por teléfono", exc_info=True)
            return None
        if pedidos:
            return await lookup_by_document(
                session, contact, variante, "telefono"
            )
    return None
