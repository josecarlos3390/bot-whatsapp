"""Mide la precisión del clasificador de intención.

Uso:
    python -m scripts.eval_intent            # reglas + modelo
    python -m scripts.eval_intent --rules    # solo reglas (sin costo)

Sirve para evaluar cambios en las reglas o en la lista de ocasiones antes de
publicarlos: si la precisión baja, no se sube.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.services import intent

CASOS = Path(__file__).resolve().parent.parent / "tests" / "data" / "intent_cases.json"


def _compare(obtenido: dict, esperado: dict) -> list[str]:
    fallas = []
    if obtenido["intent"] != esperado["intent"]:
        fallas.append("intent")
    if "buy" in esperado and obtenido["buy"] != esperado["buy"]:
        fallas.append("buy")
    if "ambiguous" in esperado and obtenido["ambiguous"] != esperado["ambiguous"]:
        fallas.append("ambiguous")
    if "occasion" in esperado and obtenido["occasion"] != esperado["occasion"]:
        fallas.append("occasion")
    return fallas


async def _report_db(limit: int, *, use_llm: bool) -> None:
    """Clasifica mensajes reales para revisar a ojo cómo está decidiendo."""
    import sqlite3

    con = sqlite3.connect("dev.db")
    rows = con.execute(
        "select text from messages where direction='in' and text is not null "
        "and length(text) between 3 and 140 order by created_at desc limit ?",
        (limit,),
    ).fetchall()
    for (text,) in reversed(rows):
        decision = (
            await intent.classify(text) if use_llm else intent.rules(text)
        )
        print(
            f"{decision['intent']:<9} | compra={str(decision['buy'])[0]} "
            f"| duda={str(decision['ambiguous'])[0]} "
            f"| ocasion={decision['occasion'] or '-':<12} | {text[:70]}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", action="store_true", help="sin modelo")
    parser.add_argument(
        "--from-db",
        type=int,
        default=0,
        help="en vez del set, clasifica los últimos N mensajes reales del bot",
    )
    args = parser.parse_args()

    if args.from_db:
        await _report_db(args.from_db, use_llm=not args.rules)
        return

    casos = json.loads(CASOS.read_text(encoding="utf-8"))["cases"]
    aciertos = 0
    for caso in casos:
        decision = (
            intent.rules(caso["text"])
            if args.rules
            else await intent.classify(caso["text"])
        )
        fallas = _compare(decision, caso)
        if fallas:
            print(f"FALLA {caso['text']!r}: {', '.join(fallas)}")
            print(f"   esperado: {caso}")
            print(f"   obtenido: {decision}")
        else:
            aciertos += 1

    total = len(casos)
    print()
    print(f"{'Reglas' if args.rules else 'Híbrido (reglas + modelo)'}: "
          f"{aciertos}/{total} = {aciertos * 100 / total:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
