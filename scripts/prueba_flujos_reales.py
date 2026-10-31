"""Pruebas de conversación como si atendiera personas de verdad.

Recorre los flujos completos: saludo, menú, categorías, subcategorías,
presupuesto, ficha, carrito, reserva, envíos, reclamos, seguimiento y
derivación. Cada paso usa el camino real (ingest) y los botones de WhatsApp.

Uso:
    python -m scripts.prueba_flujos_reales
    python -m scripts.prueba_flujos_reales --flujo menu
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Contact, Conversation
from app.services import ingest

PROHIBIDAS = (
    "gracias por contarme",
    "no pude completar",
    "contenido de ejemplo",
    "reemplazar por",
    "traceback",
)


def _campo(mensaje, nombre: str):
    """Lee un campo del mensaje, venga como objeto o como dict."""
    if isinstance(mensaje, dict):
        return mensaje.get(nombre)
    return getattr(mensaje, nombre, None)


def _texto(mensaje) -> str:
    return _campo(mensaje, "text") or ""


@dataclass
class Turno:
    envie: str
    recibido: list = field(default_factory=list)


class Persona:
    """Un cliente simulado que toca botones como lo haría una persona."""

    def __init__(self, nombre: str, numero: str) -> None:
        self.nombre = nombre
        self.numero = numero
        self.turnos: list[Turno] = []
        # A partir de este turno el bot debe callarse (derivado a un asesor).
        self.silencio_desde: int | None = None

    @property
    def ultimo(self) -> list:
        return self.turnos[-1].recibido if self.turnos else []

    def textos(self, turno: int = -1) -> str:
        mensajes = self.turnos[turno].recibido
        return " | ".join(_texto(m).replace("\n", " ") for m in mensajes)

    def opciones(self, turno: int = -1) -> list[dict]:
        """Botones o filas de lista del último mensaje con opciones."""
        mensajes = self.turnos[turno].recibido
        for mensaje in reversed(mensajes):
            botones = _campo(mensaje, "buttons") or []
            if botones:
                return [
                    {"title": b["title"], "id": b["id"]} for b in botones
                ]
            secciones = _campo(mensaje, "sections") or []
            filas = [
                fila
                for seccion in secciones
                for fila in (seccion.get("rows") or [])
            ]
            if filas:
                return [
                    {"title": fila["title"], "id": fila["id"]}
                    for fila in filas
                ]
        return []

    def buscar_opcion(self, patron: str, turno: int = -1) -> str | None:
        for opcion in self.opciones(turno):
            if re.search(patron, opcion["title"], re.IGNORECASE):
                return opcion["id"]
        return None


class Charla:
    def __init__(self, persona: Persona, session) -> None:
        self.persona = persona
        self.session = session
        self.n = 0

    async def decir(self, texto: str) -> list:
        self.n += 1
        salida = await ingest.ingest_inbound(
            self.session,
            self.persona.numero,
            texto,
            f"wamid.{uuid.uuid4().hex[:12]}",
            name=self.persona.nombre,
            deliver=False,
        )
        mensajes = list(salida or [])
        self.persona.turnos.append(Turno(envie=texto, recibido=mensajes))
        return mensajes

    async def tocar(self, patron: str) -> list | None:
        """Toca la opción si está; si no, sigue (el flujo puede variar)."""
        opcion = self.persona.buscar_opcion(patron)
        if opcion is None:
            return None
        return await self.decir(opcion)

    async def tocar_primera(self, excluir: str = "ver todo|asesor|otra") -> list | None:
        for opcion in self.persona.opciones():
            if not re.search(excluir, opcion["title"], re.IGNORECASE):
                return await self.decir(opcion["id"])
        return None


def problemas(persona: Persona) -> list[str]:
    """Revisa incoherencias en toda la conversación."""
    fallas: list[str] = []
    for indice, turno in enumerate(persona.turnos):
        textos = [
            _texto(mensaje).strip() for mensaje in turno.recibido
        ]
        juntos = " ".join(textos).lower()
        for prohibida in PROHIBIDAS:
            if prohibida in juntos:
                fallas.append(
                    f"turno {indice + 1}: aparece «{prohibida}»"
                )
        silencio = (
            persona.silencio_desde is not None
            and indice + 1 >= persona.silencio_desde
        )
        if (not textos or not any(textos)) and not silencio:
            fallas.append(f"turno {indice + 1}: respuesta vacía")
        # Mensajes repetidos en el mismo turno.
        repetidos = {
            texto for texto in textos if textos.count(texto) > 1 and texto
        }
        for repetido in repetidos:
            fallas.append(
                f"turno {indice + 1}: mensaje repetido «{repetido[:40]}»"
            )
        # Mismo listado dos veces (texto + menú).
        if len(textos) >= 2:
            primero, segundo = textos[0][:40], textos[1][:40]
            if primero and primero == segundo:
                fallas.append(f"turno {indice + 1}: listado duplicado")
    return fallas


async def _contacto(session, nombre: str) -> Persona:
    numero = f"5917{uuid.uuid4().hex[:8]}"
    persona = Persona(nombre, numero)
    contacto = Contact(
        wa_id=numero, phone_e164=f"+{numero}", name=nombre
    )
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return persona


# Cada flujo devuelve la persona para poder revisarla después.
async def flujo_saludo(session) -> Persona:
    persona = await _contacto(session, "Ana")
    charla = Charla(persona, session)
    await charla.decir("hola")
    await charla.tocar("buscar")
    await charla.decir("hola de nuevo")
    return persona


async def flujo_menu(session) -> Persona:
    persona = await _contacto(session, "Beto")
    charla = Charla(persona, session)
    await charla.decir("hola")
    await charla.tocar("buscar")
    await charla.tocar("sala")
    await charla.tocar_primera()
    await charla.tocar_primera()
    return persona


async def flujo_compra(session) -> Persona:
    persona = await _contacto(session, "Carla")
    charla = Charla(persona, session)
    await charla.decir("busco un taladro")
    await charla.tocar_primera()
    await charla.tocar_primera()
    await charla.tocar("agregar 1")
    await charla.decir("carrito")
    await charla.decir("confirmar")
    return persona


async def flujo_objecion(session) -> Persona:
    persona = await _contacto(session, "Dani")
    charla = Charla(persona, session)
    await charla.decir("busco un colchon de 2 plazas")
    await charla.tocar_primera()
    await charla.decir("es muy caro")
    await charla.tocar_primera()
    return persona


async def flujo_reserva(session) -> Persona:
    persona = await _contacto(session, "Eva")
    charla = Charla(persona, session)
    await charla.decir("busco un sofa")
    await charla.decir("para la sala")
    await charla.tocar_primera()
    if await charla.tocar("reservar") is None:
        await charla.tocar("agregar 1")
    return persona


async def flujo_envio(session) -> Persona:
    persona = await _contacto(session, "Fede")
    charla = Charla(persona, session)
    await charla.decir("hacen envios a Santa Cruz?")
    await charla.decir("cuanto cuesta el envio?")
    return persona


async def flujo_devolucion(session) -> Persona:
    persona = await _contacto(session, "Gabi")
    charla = Charla(persona, session)
    await charla.decir("me llego roto el producto y quiero devolverlo")
    for respuesta in ("ayer", "una licuadora", "si"):
        await charla.decir(respuesta)
    return persona


async def flujo_estado(session) -> Persona:
    persona = await _contacto(session, "Hugo")
    charla = Charla(persona, session)
    await charla.decir("hola")
    await charla.tocar("pedido")
    await charla.decir("12345678")
    return persona


async def flujo_ambiguo(session) -> Persona:
    persona = await _contacto(session, "Irene")
    charla = Charla(persona, session)
    await charla.decir("busco una consola")
    await charla.tocar("videojuegos")
    await charla.decir("y un monitor?")
    return persona


async def flujo_inexistente(session) -> Persona:
    persona = await _contacto(session, "Juan")
    charla = Charla(persona, session)
    await charla.decir("busco una impresora")
    await charla.decir("tienen telescopios?")
    return persona


async def flujo_asesor(session) -> Persona:
    persona = await _contacto(session, "Kari")
    charla = Charla(persona, session)
    await charla.decir("quiero hablar con una persona")
    persona.silencio_desde = len(persona.turnos) + 1
    await charla.decir("hola?")
    return persona


FLUJOS = {
    "saludo": flujo_saludo,
    "menu": flujo_menu,
    "compra": flujo_compra,
    "objecion": flujo_objecion,
    "reserva": flujo_reserva,
    "envio": flujo_envio,
    "devolucion": flujo_devolucion,
    "estado": flujo_estado,
    "ambiguo": flujo_ambiguo,
    "inexistente": flujo_inexistente,
    "asesor": flujo_asesor,
}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flujo", default="")
    parser.add_argument("--verboso", action="store_true")
    args = parser.parse_args()

    elegidos = (
        {args.flujo: FLUJOS[args.flujo]}
        if args.flujo
        else FLUJOS
    )
    total_fallas = 0
    async with SessionLocal() as session:
        for nombre, funcion in elegidos.items():
            persona = await funcion(session)
            fallas = problemas(persona)
            total_fallas += len(fallas)
            estado = "OK" if not fallas else f"{len(fallas)} falla(s)"
            print(f"\n=== {nombre} [{estado}]")
            for turno in persona.turnos:
                primera = (
                    _texto(turno.recibido[0]).replace("\n", " ")[:100]
                    if turno.recibido
                    else "(sin respuesta)"
                )
                print(f"  > {turno.envie[:40]!r}")
                print(f"    < {primera}")
            for falla in fallas:
                print(f"  ✗ {falla}")

    print(f"\nflujos: {len(elegidos)} | fallas: {total_fallas}")
    return 1 if total_fallas else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
