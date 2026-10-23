"""Detección de intenciones ambiguas y preguntas de desambiguación."""

from __future__ import annotations

import re

AMBIGUOUS: list[tuple[re.Pattern[str], re.Pattern[str], str, str]] = [
    (
        re.compile(r"\bestado\b", re.I),
        re.compile(
            r"\b(pedido|orden|env[ií]o|producto|compra|factura|seguimiento)\b",
            re.I,
        ),
        "¿Querés consultar el estado del pedido o el estado de un producto?",
        "estado",
    ),
    (
        re.compile(r"\bentrega\b", re.I),
        re.compile(
            r"\b(env[ií]o|pedido|domicilio|seguimiento|fecha|demora)\b", re.I
        ),
        "¿Consultás el envío o querés hablar con un asesor?",
        "entrega",
    ),
    (
        re.compile(r"\bcambio\b", re.I),
        re.compile(
            r"\b(producto|direcci[oó]n|pago|color|talla|modelo)\b", re.I
        ),
        "¿Es un cambio de producto, de dirección o de forma de pago?",
        "cambio",
    ),
    (
        re.compile(r"\b(pago|pagar|pagado)\b", re.I),
        re.compile(
            r"\b(qr|tarjeta|transferencia|cuotas?|efectivo|pedido|factura|"
            r"link|pasarela)\b",
            re.I,
        ),
        "¿Consultás los medios de pago o el estado de un pago?",
        "pago",
    ),
    (
        re.compile(r"\bcancelar\b", re.I),
        re.compile(r"\b(pedido|devoluci[oó]n|carrito|compra|orden)\b", re.I),
        "¿Querés cancelar un pedido, una devolución o el carrito?",
        "cancelar",
    ),
    (
        re.compile(r"\bfactura\b", re.I),
        re.compile(
            r"\b(compra|pedido|empresa|nit|facturaci[oó]n|documento)\b", re.I
        ),
        "¿Necesitás la factura de una compra o facturación para empresa?",
        "factura",
    ),
    (
        re.compile(r"\bgarant[ií]a\b", re.I),
        re.compile(r"\b(producto|reclamo|devoluci[oó]n|defecto)\b", re.I),
        "¿Consultás la garantía de un producto o querés iniciar un reclamo?",
        "garantia",
    ),
    (
        re.compile(r"\bno\s+me\s+lleg[oó]\b", re.I),
        re.compile(r"\b(pedido|env[ií]o|reclamo|demora)\b", re.I),
        "¿Querés seguimiento del pedido o presentar un reclamo?",
        "no_llego",
    ),
    (
        re.compile(r"^\s*[\d.,]+\s*$", re.I),
        re.compile(r"$^"),
        "¿Ese número es una medida en pulgadas, plazas, unidades o un presupuesto en bolivianos?",
        "numero",
    ),
    (
        re.compile(r"\b(regalo|regalar)\b", re.I),
        re.compile(
            r"\b(ocasi[oó]n|cumplea[nñ]os|navidad|presupuesto|categor[ií]a|"
            r"mam[aá]|pap[aá]|ni[nñ]o)\b",
            re.I,
        ),
        "¿Buscás por ocasión, por presupuesto o por categoría?",
        "regalo",
    ),
    (
        re.compile(r"\bprecio\s+por\s+mayor\b", re.I),
        re.compile(r"\b(unidades|cantidad|docena|mayorista)\b", re.I),
        "¿Cuántas unidades necesitás para cotizarte por mayor?",
        "mayor",
    ),
    (
        re.compile(r"\bdisponible\b", re.I),
        re.compile(
            r"\b(producto|stock|retiro|tienda|sucursal|modelo|sku)\b", re.I
        ),
        "¿Consultás disponibilidad de un producto o retiro en tienda?",
        "disponible",
    ),
    (
        re.compile(r"\bel\s+primero\b", re.I),
        re.compile(r"$^"),
        "¿El primero de qué lista? Si querés, decime el producto y te ayudo a ubicarlo.",
        "primero",
    ),
]


def detect(text: str | None) -> str | None:
    """Devuelve una pregunta si el mensaje es ambiguo; None si es claro."""
    value = (text or "").strip()
    if not value:
        return None
    for trigger, context, question, _key in AMBIGUOUS:
        if not trigger.search(value):
            continue
        if context.search(value):
            continue
        return question
    return None


def route_answer(text: str | None) -> str | None:
    """Clasifica la respuesta del cliente a una pregunta de desambiguación."""
    value = (text or "").lower()
    if re.search(r"\b(asesor|humano|persona)\b", value):
        return "human"
    if re.search(r"\b(pedido|orden|seguimiento|no me lleg)\b", value):
        return "order"
    if re.search(r"\b(devoluci[oó]n|devolver|garant[ií]a|reclamo)\b", value):
        return "return"
    if re.search(r"\b(env[ií]o|entrega|retiro|sucursal|domicilio)\b", value):
        return "shipping"
    if re.search(r"\b(pago|qr|tarjeta|transferencia|cuota)\b", value):
        return "payment"
    if re.search(r"\b(factura|facturaci[oó]n)\b", value):
        return "invoice"
    if re.search(r"\b(regalo|ocasi[oó]n)\b", value):
        return "gift"
    if re.search(r"\b(producto|stock|modelo|pulgadas|plazas|unidades)\b", value):
        return "product"
    if re.search(r"\b(cancelar|carrito)\b", value):
        return "cancel"
    return None
