"""Un mensaje, una pregunta: poda de cierres repetidos.

Cada flujo arma su propia respuesta y, a veces, agrega un cierre de más
(«¿Te muestro el detalle o buscamos otra cosa?») justo después de una lista
que ya preguntaba lo mismo. Esto lo quita en un solo lugar.
"""

from __future__ import annotations

from ..whatsapp import Outbound

# Botones genéricos: no aportan si ya hay una lista antes.
_GENERICOS = {"catalog", "human", "asesor", "search"}

# Cierres que sí se agregan después de la lista a propósito.
_INTENCIONALES = ("para asesorarte mejor",)


def _es_cierre_generico(mensaje: Outbound) -> bool:
    if mensaje.kind not in {"buttons", "list"}:
        return False
    ids = {boton.get("id") for boton in (mensaje.buttons or [])}
    if not ids:
        return mensaje.kind == "buttons" and not mensaje.sections
    return bool(ids) and ids <= _GENERICOS


def _es_pregunta_repetida(texto: str) -> bool:
    valor = (texto or "").strip().lower()
    if not valor.endswith("?"):
        return False
    return any(
        clave in valor
        for clave in (
            "te muestro el detalle",
            "te muestro más opciones",
            "te muestro mas opciones",
            "te interesa alguna",
            "buscamos otra cosa",
            "hablamos con un asesor",
            "querés ver otra cosa",
            "quieres ver otra cosa",
        )
    )


def podar(mensajes: list[Outbound]) -> list[Outbound]:
    """Quita cierres de más cuando ya hay una lista o un cierre antes."""
    if len(mensajes) < 2:
        return mensajes

    primero_cierre = next(
        (
            indice
            for indice, mensaje in enumerate(mensajes)
            if mensaje.kind in {"list", "buttons"}
        ),
        None,
    )
    if primero_cierre is None:
        return _sin_repetidos(mensajes)

    salida = list(mensajes[: primero_cierre + 1])
    for mensaje in mensajes[primero_cierre + 1 :]:
        texto = (mensaje.text or "").strip().lower()
        if mensaje.kind in {"list", "buttons"} and _es_cierre_generico(mensaje):
            continue
        if mensaje.kind == "text":
            if any(clave in texto for clave in _INTENCIONALES):
                salida.append(mensaje)
                continue
            if _es_pregunta_repetida(texto):
                continue
        salida.append(mensaje)
    return _sin_repetidos(salida)


def _sin_repetidos(mensajes: list[Outbound]) -> list[Outbound]:
    """Elimina dos mensajes de texto idénticos seguidos."""
    salida: list[Outbound] = []
    for mensaje in mensajes:
        if (
            salida
            and mensaje.kind == "text"
            and salida[-1].kind == "text"
            and (mensaje.text or "").strip()
            and (mensaje.text or "").strip()
            == (salida[-1].text or "").strip()
        ):
            continue
        salida.append(mensaje)
    return salida
