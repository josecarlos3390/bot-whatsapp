"""Seguimiento por CI/NIT cuando el cliente no tiene el número de pedido."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact
from .order_tracking import (
    STATUS_GUIDE,
    STATUS_LABELS,
    _date,
    _money,
    format_order,
)

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


def _digitos(valor: str) -> str:
    import re

    return re.sub(r"\D", "", str(valor or ""))


async def _solo_del_cliente(
    sap, pedidos: list[dict], dato: str, kind: str
) -> list[dict]:
    """Deja solo los pedidos que pertenecen al dato que dio el cliente.

    El endpoint del integrador acepta documento O número de secuencia. Si un
    cliente escribe un número que coincide con la secuencia de otro pedido,
    devolvería un pedido ajeno: se verifica contra el perfil del pedido.
    """
    buscado = _digitos(dato)
    if not buscado:
        return pedidos
    verificados: list[dict] = []
    for pedido in pedidos[:5]:
        numero = str(pedido.get("orderId") or "")
        if not numero:
            continue
        try:
            detalle = await sap.get_order(numero)
        except Exception:  # noqa: BLE001 - sin detalle no se muestra
            logger.debug("No se pudo verificar el pedido %s", numero)
            continue
        perfil = (detalle or {}).get("clientProfileData") or {}
        documento = _digitos(perfil.get("document"))
        telefono = _digitos(perfil.get("phone"))
        if kind == "telefono":
            coincide = bool(telefono) and (
                telefono.endswith(buscado) or buscado.endswith(telefono)
            )
        else:
            coincide = documento == buscado
        if coincide:
            verificados.append(detalle)
    return verificados


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
            # después sus compras por documento. La verificación pasa a usar
            # el documento, que es el dato que realmente resolvió.
            cliente = await sap.get_customer(documento)
            documento_cliente = str((cliente or {}).get("document") or "")
            if documento_cliente:
                pedidos = await sap.get_customer_purchases(
                    documento_cliente, top=5, skip=0
                )
                if pedidos:
                    documento = documento_cliente
                    kind = "carnet"
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

    # El endpoint acepta documento O número de secuencia: si alguien escribe
    # un número que coincide con la secuencia de otro pedido, devolvería el
    # pedido de otra persona. Se verifica el documento del pedido antes de
    # mostrarlo.
    pedidos = await _solo_del_cliente(sap, pedidos, documento, kind)

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


EMAIL_RE = __import__("re").compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


def extract_email(text: str) -> str | None:
    """Email dentro del mensaje, si lo hay."""
    match = EMAIL_RE.search(text or "")
    return match.group(0).strip().lower() if match else None


async def lookup_by_email(
    session: AsyncSession, contact: Contact, email: str
) -> dict:
    """Busca pedidos por email y verifica que sean del cliente."""
    from ..sap import SapError, get_sap

    email = (email or "").strip().lower()
    if not email:
        return {
            "text": "Pasame un email válido y busco tus compras.",
            "finished": False,
            "needs_handoff": False,
        }
    try:
        sap = get_sap(session)
        pedidos = await sap.get_customer_purchases(email, top=5, skip=0)
        # El email de la cuenta (CL.email) es la llave; el de la orden puede
        # ser anónimo (@ct.vtex). Se valida por el documento de la cuenta.
        cuenta = await sap.get_customer(email)
        documento_cuenta = _digitos((cuenta or {}).get("document"))
        verificados = []
        for pedido in pedidos[:5]:
            numero = str(pedido.get("orderId") or "")
            if not numero:
                continue
            try:
                detalle = await sap.get_order(numero)
            except Exception:  # noqa: BLE001
                continue
            perfil = (detalle or {}).get("clientProfileData") or {}
            documento = _digitos(perfil.get("document"))
            correo = str(perfil.get("email") or "").strip().lower()
            if documento_cuenta:
                if documento and documento == documento_cuenta:
                    verificados.append(detalle)
            elif correo == email:
                verificados.append(detalle)
        pedidos = verificados
    except SapError:
        logger.exception("No se pudo consultar por email")
        return {
            "text": (
                "No pude consultar el sistema ahora. "
                "¿Querés que te pase con un asesor?"
            ),
            "finished": True,
            "needs_handoff": True,
        }

    if not pedidos:
        return {
            "text": (
                f"No encontré compras con el email *{email}*. "
                "Puede ser que la compra esté con otro correo.\n\n"
                "¿Querés probar con tu CI/NIT o que te derive con un asesor?"
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

    lineas = [f"Encontré *{len(pedidos)} compras* con ese email:", ""]
    for pedido in pedidos[:5]:
        numero = pedido.get("orderId") or "—"
        fecha = _date(pedido.get("creationDate"))
        total = _money(pedido.get("value") or 0)
        estado = str(pedido.get("status") or "").strip() or "—"
        lineas.append(f"• {numero} · {fecha} · Bs {total} · {estado}")
    lineas.append("")
    lineas.append("Decime cuál te interesa y te muestro el detalle.")
    return {
        "text": "\n".join(lineas),
        "finished": True,
        "needs_handoff": False,
    }


async def lookup_by_sequence(session: AsyncSession, sequence: str) -> dict | None:
    """Estado del pedido por número de secuencia, sin datos personales.

    La secuencia no identifica a una persona: solo se usa cuando el cliente
    la tiene a mano y se muestra el estado y los productos, nunca nombre,
    dirección ni documento.
    """
    from ..config import settings
    from ..sap import SapError, get_sap

    if not settings.order_sequence_lookup_enabled:
        return None
    numero = _digitos(sequence)
    if not numero:
        return None
    try:
        sap = get_sap(session)
        metodo = getattr(sap, "get_order_by_sequence", None)
        if metodo is None:
            return None
        pedido = await metodo(numero)
    except SapError:
        return None
    except Exception:  # noqa: BLE001
        logger.debug("Fallo la búsqueda por secuencia", exc_info=True)
        return None
    if not pedido:
        return None
    estado = str(pedido.get("status") or "")
    etiqueta = STATUS_LABELS.get(estado, pedido.get("statusDescription") or estado)
    lineas = [
        f"Pedido *{numero}*",
        f"Estado: *{etiqueta}*",
    ]
    guia = STATUS_GUIDE.get(estado)
    if guia:
        lineas.append(guia[1])
    # El resumen de secuencia no trae artículos: se piden al detalle, pero
    # solo se usan estado, productos y fecha (nunca datos personales).
    items = pedido.get("items") or []
    if not items and pedido.get("orderId"):
        try:
            detalle = await get_sap(session).get_order(str(pedido.get("orderId")))
            items = (detalle or {}).get("items") or []
        except Exception:  # noqa: BLE001
            items = []
    fecha = pedido.get("ShippingEstimatedDate") or pedido.get("shippingEstimatedDate")
    if fecha:
        lineas.append(f"Entrega estimada: {_date(str(fecha))}")
    if items:
        lineas.append("Productos:")
        for item in items[:5]:
            nombre = item.get("name") or item.get("skuName") or "Producto"
            lineas.append(f"• {item.get('quantity') or 1} × {nombre}")
    lineas.append("\nPor seguridad no muestro datos personales de este pedido.")
    return {
        "text": "\n".join(lineas),
        "finished": True,
        "needs_handoff": False,
    }
