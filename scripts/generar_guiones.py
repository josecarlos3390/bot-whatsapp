"""Genera guiones de auditoría con IA: respuestas naturales reales.

Para cada pregunta que hace el bot, le pide al modelo varias formas en que un
cliente podría contestar. Con eso se arman casos de auditoría sin escribirlos
a mano.

Uso:
    python -m scripts.generar_guiones --por-pregunta 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings

SALIDA = Path("scripts") / "guiones_generados.json"

# Pregunta del bot -> contexto previo para llegar a esa pregunta.
PREGUNTAS = [
    {
        "id": "marca",
        "contexto": "busco un colchón",
        "pregunta": "¿Alguna marca en particular o te muestro las más elegidas?",
        "espera": ["colchón", "colchon", "opciones", "marca", "Bs"],
    },
    {
        "id": "medida",
        "contexto": "busco un colchón",
        "pregunta": "¿Qué medida te sirve?",
        "espera": ["colchón", "colchon", "plazas", "medida", "Bs"],
    },
    {
        "id": "seguir",
        "contexto": "busco un taladro",
        "pregunta": "¿Te muestro más opciones o hablamos con un asesor?",
        "espera": ["opción", "opcion", "taladro", "asesor", "Bs"],
    },
]

PROMPT = """Sos un cliente que escribe por WhatsApp a un homecenter.
El bot te acaba de preguntar: "{pregunta}"
Contexto de la charla: {contexto}

Escribí UNA respuesta corta, natural, como lo haría una persona real
(sin comillas, sin explicaciones, máximo 12 palabras).
Variante pedida: número {indice}, distinta de las anteriores.
Respondé solo la frase."""


async def generar(por_pregunta: int) -> dict:
    cliente = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )
    casos: list[dict] = []
    for pregunta in PREGUNTAS:
        respuestas: list[str] = []
        for indice in range(por_pregunta):
            try:
                completado = await cliente.chat.completions.create(
                    model=settings.deepseek_model,
                    messages=[
                        {
                            "role": "user",
                            "content": PROMPT.format(
                                pregunta=pregunta["pregunta"],
                                contexto=pregunta["contexto"],
                                indice=indice + 1,
                            ),
                        }
                    ],
                    temperature=0.9,
                    max_tokens=60,
                    # Igual que el resto del bot: sin esto el modelo
                    # devuelve contenido vacío.
                    extra_body={"thinking": {"type": "disabled"}},
                )
                texto = (completado.choices[0].message.content or "").strip()
            except Exception:  # noqa: BLE001 - se sigue con las demás
                continue
            texto = texto.strip('"').strip()
            if 2 <= len(texto) <= 80 and texto not in respuestas:
                respuestas.append(texto)
        for respuesta in respuestas:
            casos.append(
                {
                    "id": f"{pregunta['id']}-{len(casos) + 1}",
                    "mensajes": [pregunta["contexto"], respuesta],
                    "espera": pregunta["espera"],
                }
            )
    await cliente.close()
    return {"casos": casos}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--por-pregunta", type=int, default=4)
    args = parser.parse_args()

    datos = await generar(args.por_pregunta)
    SALIDA.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"casos generados: {len(datos['casos'])} → {SALIDA}")
    for caso in datos["casos"][:6]:
        print("  ", caso["mensajes"][-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
