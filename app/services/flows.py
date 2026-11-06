"""WhatsApp Flows del checkout: facturación y entrega.

Dos formularios nativos, uno por forma de entrega:

- **Tienda**: solo datos de facturación.
- **Domicilio**: datos de entrega + facturación.

El cliente completa el formulario dentro de WhatsApp; el JSON vuelve como
`interactive.nfm_reply` y acá se interpreta.
"""

from __future__ import annotations

import json
import logging

from ..config import settings

logger = logging.getLogger(__name__)

CAMPOS = (
    "metodo",
    "nombre_recibe",
    "direccion",
    "referencia",
    "nombre_factura",
    "documento",
)

TIENDA = "tienda"
DOMICILIO = "domicilio"

# Sucursales para retiro (knowledge/sucursales.md).
TIENDAS = [
    (
        "Zona Norte",
        "Av. Banzer, 3er anillo interno, frente a Hipermaxi",
        "Lun a sáb 08:00–21:00 · dom 08:30–21:00",
    ),
    (
        "Zona Este",
        "2do anillo, entre Av. Virgen de Cotoca y Canal Cotoca",
        "Lun a sáb 08:00–21:00 · dom 08:30–21:00",
    ),
    (
        "Las Palmas · Zona Sur",
        "Av. Grigotá y 4to anillo, barrio Las Palmas",
        "Confirmar horarios con atención al cliente",
    ),
]


def es_respuesta(texto: str) -> bool:
    """¿El texto es el JSON que devuelve un Flow?"""
    valor = (texto or "").strip()
    if not valor.startswith("{") or not valor.endswith("}"):
        return False
    try:
        datos = json.loads(valor)
    except ValueError:
        return False
    return isinstance(datos, dict) and (
        "metodo" in datos or "nombre_factura" in datos or "direccion" in datos
    )


def leer(texto: str) -> dict[str, str]:
    """Devuelve solo los campos conocidos, limpios."""
    try:
        datos = json.loads(texto)
    except ValueError:
        return {}
    if not isinstance(datos, dict):
        return {}
    limpio: dict[str, str] = {}
    for campo in CAMPOS:
        valor = datos.get(campo)
        if isinstance(valor, str) and valor.strip():
            limpio[campo] = valor.strip()[:300]
    return limpio


def mensaje_elegir_entrega() -> dict:
    """Botones para elegir tienda o domicilio antes del formulario."""
    return {
        "kind": "buttons",
        "text": (
            "¿Cómo querés recibir tu pedido?\n\n"
            "🏬 *Retiro en tienda*: sin costo, listo el mismo día.\n"
            "🚚 *Envío a domicilio*: coordinamos la entrega."
        ),
        "buttons": [
            {"id": "entrega:tienda", "title": "Retiro en tienda"},
            {"id": "entrega:domicilio", "title": "Envío a domicilio"},
        ],
    }


def mensaje_pedir_datos(metodo: str, token: str = "") -> dict | None:
    """Payload del mensaje interactivo que abre el formulario."""
    flow_id = (
        settings.wa_flow_facturacion
        if metodo == TIENDA
        else settings.wa_flow_entrega
    )
    if not flow_id:
        return None
    titulo = (
        "Datos de facturación"
        if metodo == TIENDA
        else "Datos de entrega y facturación"
    )
    texto = (
        "Como lo retirás en tienda, solo necesitamos los datos de la factura."
        if metodo == TIENDA
        else "Completá los datos de entrega y de facturación."
    )
    parametros = {
        "flow_message_version": "3",
        "flow_id": flow_id,
        "flow_cta": "Completar datos",
        "flow_action": "navigate",
        "flow_action_payload": {
            "screen": "FACTURACION" if metodo == TIENDA else "ENTREGA"
        },
    }
    if token:
        parametros["flow_token"] = token
    return {
        "kind": "flow",
        "text": texto,
        "flow_header": titulo,
        "flow_parameters": parametros,
    }


def confirmacion(datos: dict[str, str]) -> str:
    """Mensaje que confirma los datos recibidos."""
    lineas = ["✅ ¡Gracias! Guardé tus datos:"]
    if datos.get("nombre_recibe"):
        lineas.append(f"👤 Recibe: {datos['nombre_recibe']}")
    if datos.get("direccion"):
        lineas.append(f"📍 {datos['direccion']}")
    if datos.get("referencia"):
        lineas.append(f"🧭 {datos['referencia']}")
    if datos.get("nombre_factura"):
        lineas.append(f"🧾 Factura a nombre de: {datos['nombre_factura']}")
    if datos.get("documento"):
        lineas.append(f"🪪 Documento: {datos['documento']}")
    return "\n".join(lineas)


def texto_tiendas() -> str:
    """Ubicaciones de las tres tiendas para retiro."""
    lineas = ["🏬 *Podés retirar en cualquiera de nuestras tiendas:*", ""]
    for nombre, direccion, horario in TIENDAS:
        lineas.append(f"*{nombre}*")
        lineas.append(f"📍 {direccion}")
        lineas.append(f"🕒 {horario}")
        lineas.append("")
    lineas.append("Cuando esté listo te avisamos para que pases a buscarlo.")
    return "\n".join(lineas)
