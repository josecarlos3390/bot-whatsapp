"""Simula conversaciones con clientes y evalúa las respuestas.

Un modelo hace de cliente (con un objetivo) y otro evalúa el resultado. Sirve
para encontrar combinaciones que a un humano no se le ocurren, sin usar
WhatsApp real ni ensuciar datos.

Uso:
    python -m scripts.fuzz_conversations --conversaciones 5 --turnos 6
    python -m scripts.fuzz_conversations --solo-reglas    # sin costo de modelo

Cada conversación usa un contacto temporal que se borra al terminar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import uuid
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import delete

from app.agent import Agent
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Contact,
    Conversation,
    CustomerProfile,
    FunnelEvent,
    Handoff,
    Message,
)

PERSONAS = [
    "Busco un colchón de 2 plazas, con presupuesto ajustado.",
    "Quiero un televisor de 50 pulgadas; si hay OLED, mejor.",
    "Pregunto por el envío a Santa Cruz y los plazos.",
    "Necesito algo para regalar en un cumpleaños, no sé qué.",
    "Quiero comparar dos licuadoras y saber cuál conviene.",
    "Consulto la garantía de una lavadora.",
    "Tengo un problema con un pedido anterior y estoy molesto.",
    "Quiero amueblar un living chico con poco presupuesto.",
]


# Casos fijos de regresión: se repiten todos los meses para comparar.
# Cada uno nació de un bug real encontrado por el fuzzing.
ESCENARIOS = [
    {
        "id": "pedido-id",
        "persona": "Pedí una heladera y me llegó una cocina. Tengo el ID del pedido a mano.",
        "primer_mensaje": "Hola, me llegó un producto equivocado y tengo el número de pedido",
    },
    {
        "id": "stock",
        "persona": "Quiero saber si hay stock de un producto para hoy.",
        "primer_mensaje": "¿Tenés stock disponible para hoy?",
    },
    {
        "id": "envio-zona",
        "persona": "Necesito saber si envían a mi ciudad.",
        "primer_mensaje": "¿Hacen envíos a Santa Cruz capital?",
    },
    {
        "id": "enojo",
        "persona": "Estoy muy molesto y quiero que me atienda una persona.",
        "primer_mensaje": "Ya me cansé, quiero hablar con una persona",
    },
    {
        "id": "precio",
        "persona": "Busco un televisor y me interesa el más barato.",
        "primer_mensaje": "¿Cuál es el televisor más barato que tenés?",
    },
    {
        "id": "imagen",
        "persona": "Voy a mandar una foto de una brocha y quiero comprar algo igual.",
        "primer_mensaje": "Te mando una foto, quiero comprar algo así",
    },
]

JUEZ = """Eres un evaluador de calidad de un chatbot de ventas.
Te paso una conversación entre un cliente y el bot. Evalúa SOLO el desempeño del bot.

Devuelve JSON con este formato exacto:
{"nota": 1-5, "problemas": ["..."], "correcto": true|false,
 "criterios": {"responde": 0-2, "no_inventa": 0-2, "no_repite": 0-2,
                "siguiente_paso": 0-2, "tono": 0-2}}

En "criterios" poné 2 si cumple, 1 si cumple a medias y 0 si falla.

Criterios:
- Responde lo que el cliente preguntó (no otro tema).
- No inventa productos, precios ni plazos.
- No repite frases ni se traba.
- Ofrece un siguiente paso claro.
- Si el cliente está molesto o cuenta algo delicado, responde con empatía.
"""


async def _cliente_habla(cliente: AsyncOpenAI, persona: str, historial: list[str]) -> str:
    mensajes = [
        {
            "role": "system",
            "content": (
                "Sos un cliente que escribe por WhatsApp a un homecenter. "
                f"Tu objetivo: {persona}\n"
                "Escribí un solo mensaje corto, como lo haría una persona real "
                "(sin comillas, sin explicaciones)."
            ),
        }
    ]
    for linea in historial[-6:]:
        mensajes.append({"role": "user", "content": linea})
    respuesta = await cliente.chat.completions.create(
        model=settings.deepseek_model,
        messages=mensajes,
        temperature=0.3,
        max_tokens=80,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return (respuesta.choices[0].message.content or "").strip().strip('"')


async def _evalua(cliente: AsyncOpenAI, transcripcion: str) -> dict:
    respuesta = await cliente.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": JUEZ},
            {"role": "user", "content": transcripcion},
        ],
        temperature=0,
        max_tokens=300,
        extra_body={"thinking": {"type": "disabled"}},
    )
    texto = respuesta.choices[0].message.content or "{}"
    try:
        inicio = texto.find("{")
        return json.loads(texto[inicio:]) if inicio >= 0 else {}
    except ValueError:
        return {}


async def _limpiar(session, contact_id: str, conversation_id: str) -> None:
    await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    await session.execute(
        delete(Handoff).where(Handoff.conversation_id == conversation_id)
    )
    await session.execute(
        delete(FunnelEvent).where(FunnelEvent.contact_id == contact_id)
    )
    await session.execute(
        delete(CustomerProfile).where(CustomerProfile.contact_id == contact_id)
    )
    await session.execute(
        delete(Conversation).where(Conversation.id == conversation_id)
    )
    await session.execute(delete(Contact).where(Contact.id == contact_id))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversaciones", type=int, default=5)
    parser.add_argument("--turnos", type=int, default=6)
    parser.add_argument("--solo-reglas", action="store_true")
    parser.add_argument(
        "--escenarios",
        action="store_true",
        help="Usa los casos fijos de regresión (recomendado para comparar meses).",
    )
    parser.add_argument(
        "--repeticiones",
        type=int,
        default=1,
        help="Cuántas veces se corre cada escenario (se usa la mediana).",
    )
    parser.add_argument(
        "--comparar",
        action="store_true",
        help="Compara con la última corrida guardada en el historial.",
    )
    args = parser.parse_args()

    cliente = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    resultados: list[dict] = []

    async with SessionLocal() as session:
        base = (
            ESCENARIOS[: args.conversaciones]
            if args.escenarios
            else [
                {"id": f"libre-{i}", "persona": random.choice(PERSONAS), "primer_mensaje": ""}
                for i in range(args.conversaciones)
            ]
        )
        # Cada escenario se repite: se compara la mediana, no una pasada.
        casos = [
            caso
            for caso in base
            for _ in range(max(1, args.repeticiones))
        ]
        for indice, caso in enumerate(casos):
            persona = caso["persona"]
            sufijo = uuid.uuid4().hex[:10]
            contact = Contact(
                wa_id=f"fuzz{sufijo}",
                phone_e164=f"+{sufijo[:9]}",
                name="Fuzz",
            )
            session.add(contact)
            await session.flush()
            conversation = Conversation(contact_id=contact.id)
            session.add(conversation)
            await session.commit()

            historial: list[str] = []
            agente = Agent()
            print(f"\n=== Conversación {indice + 1} [{caso['id']}]: {persona}")
            for turno in range(args.turnos):
                if turno == 0 and caso.get("primer_mensaje"):
                    texto = caso["primer_mensaje"]
                elif args.solo_reglas:
                    texto = "¿y qué más tenés?"
                else:
                    texto = await _cliente_habla(cliente, persona, historial)
                if not texto:
                    break
                historial.append(f"Cliente: {texto}")
                respuesta = await agente.handle(session, contact, texto)
                # Igual que en producción: el postproceso evita repeticiones.
                respuesta = await agente.postprocess(
                    session, contact, texto, respuesta
                )
                salida = " ".join(m.text or "" for m in respuesta.messages)
                historial.append(f"Bot: {salida[:400]}")
                # Igual que en producción: se guardan los mensajes para que
                # los guards de repetición tengan historial real que revisar.
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        wa_message_id=f"fuzz-in-{uuid.uuid4().hex[:12]}",
                        direction="in",
                        type="text",
                        text=texto,
                    )
                )
                session.add(
                    Message(
                        conversation_id=conversation.id,
                        wa_message_id=f"fuzz-out-{uuid.uuid4().hex[:12]}",
                        direction="out",
                        type="text",
                        text=salida,
                    )
                )
                await session.commit()
                print(f"  C: {texto[:110]}")
                print(f"  B: {salida.replace(chr(10), ' ')[:150]}")

            transcripcion = "\n".join(historial)
            evaluacion = (
                {"nota": 0, "problemas": ["sin evaluar (modo reglas)"], "correcto": False}
                if args.solo_reglas
                else await _evalua(cliente, transcripcion)
            )
            resultados.append(
                {
                    "escenario": caso["id"],
                    "persona": persona,
                    "nota": evaluacion.get("nota"),
                    "criterios": evaluacion.get("criterios"),
                    "correcto": evaluacion.get("correcto"),
                    "problemas": evaluacion.get("problemas"),
                    "transcripcion": transcripcion,
                }
            )
            print(f"  >> nota {evaluacion.get('nota')} | problemas: {evaluacion.get('problemas')}")
            await _limpiar(session, contact.id, conversation.id)

    salida = Path(".tools/fuzz-report.json")
    salida.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    notas = [r["nota"] for r in resultados if isinstance(r["nota"], (int, float))]
    from scripts import fuzz_scores

    agregado = fuzz_scores.agregar(resultados)
    resumen = {
        "fecha": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "escenarios": args.escenarios,
        "casos": agregado.get("escenarios_evaluados"),
        "repeticiones": max(1, args.repeticiones),
        "promedio": agregado["promedio"],
        "criterios": agregado["criterios"],
        "por_escenario": agregado["por_escenario"],
    }
    historial_path = Path("logs/fuzz-history.json")
    historial_path.parent.mkdir(parents=True, exist_ok=True)
    historial = []
    if historial_path.exists():
        try:
            historial = json.loads(historial_path.read_text(encoding="utf-8"))
        except ValueError:
            historial = []
    anterior = historial[-1] if historial else None
    historial.append(resumen)
    historial_path.write_text(
        json.dumps(historial[-24:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n--- resumen ---")
    print(f"conversaciones: {len(resultados)}")
    for linea in fuzz_scores.comparar(anterior if args.comparar else None, resumen):
        print(linea)
    print(f"criterios: {resumen['criterios']}")
    for escenario, datos in resumen.get("por_escenario", {}).items():
        print(f"  {escenario}: {datos['nota']} ({datos['repeticiones']} corridas)")
    if notas:
        print(f"nota promedio: {sum(notas) / len(notas):.2f}")
    print(f"informe: {salida}")


if __name__ == "__main__":
    asyncio.run(main())
