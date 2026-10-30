"""Validar la base de conocimiento antes de publicarla.

Revisa que cada archivo .md tenga título, estado y etiquetas, que no queden
marcadores sin completar y que el contenido no esté vacío.

Uso:
    python -m scripts.validar_conocimiento
"""

from __future__ import annotations

import argparse
from pathlib import Path

CARPETA = Path("knowledge")
OBLIGATORIOS = ("title", "status", "tags")
ESTADOS = {"published", "draft", "archived"}


def validar(carpeta: Path) -> tuple[list[str], list[str]]:
    """Devuelve (problemas, advertencias)."""
    problemas: list[str] = []
    advertencias: list[str] = []
    for archivo in sorted(carpeta.glob("*.md")):
        if archivo.name.lower().startswith("readme"):
            continue  # documentación de la carpeta, no es un artículo
        texto = archivo.read_text(encoding="utf-8")
        nombre = archivo.name
        if not texto.startswith("---"):
            problemas.append(f"{nombre}: falta el encabezado (---)")
            continue
        partes = texto.split("---", 2)
        if len(partes) < 3:
            problemas.append(f"{nombre}: encabezado incompleto")
            continue
        meta: dict[str, str] = {}
        for linea in partes[1].splitlines():
            if ":" in linea:
                clave, valor = linea.split(":", 1)
                meta[clave.strip().lower()] = valor.strip()
        for campo in OBLIGATORIOS:
            if not meta.get(campo):
                problemas.append(f"{nombre}: falta «{campo}»")
        estado = (meta.get("status") or "").lower()
        if estado and estado not in ESTADOS:
            problemas.append(f"{nombre}: estado desconocido «{estado}»")
        if estado == "published" and len(partes[2].strip()) < 80:
            problemas.append(f"{nombre}: contenido muy corto para publicado")
        if "TODO" in texto or "Completar" in texto:
            advertencias.append(f"{nombre}: tiene marcadores sin completar")
        if meta.get("sample", "").lower() in {"true", "si", "sí", "1"}:
            advertencias.append(f"{nombre}: marcado como ejemplo (sample)")
    return problemas, advertencias


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--carpeta", default=str(CARPETA))
    args = parser.parse_args()

    problemas, advertencias = validar(Path(args.carpeta))
    for aviso in advertencias:
        print(f"AVISO  {aviso}")
    for problema in problemas:
        print(f"FALLA  {problema}")

    total = len(list(Path(args.carpeta).glob("*.md")))
    print(f"\narchivos: {total} | problemas: {len(problemas)} | avisos: {len(advertencias)}")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
