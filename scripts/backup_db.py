"""Copia de seguridad diaria de la base y la configuración.

Crea una carpeta por día con:
- la base (SQLite: copia consistente; PostgreSQL: volcado con pg_dump),
- .env (credenciales y configuración),
- la carpeta knowledge/ (políticas y FAQ).

Conserva las últimas N copias y borra las más viejas.

Uso:
    python -m scripts.backup_db
    python -m scripts.backup_db --keep 30 --dir D:\\backups
    python -m scripts.backup_db --verificar backups/20261030-050000
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger("backup")

SQLITE = "sqlite"


def _url() -> str:
    from app.config import settings

    return settings.database_url


def _db_path() -> Path:
    url = _url()
    if not url.startswith(SQLITE):
        raise SystemExit("La base no es SQLite")
    # sqlite+aiosqlite:///./dev.db
    raw = url.split("///", 1)[-1]
    return Path(raw).resolve()


def _partes_postgres() -> dict:
    """Host, puerto, usuario, clave y base desde DATABASE_URL."""
    limpio = _url().replace("postgresql+asyncpg://", "postgresql://")
    datos = urlparse(limpio)
    return {
        "host": datos.hostname or "127.0.0.1",
        "port": datos.port or 5432,
        "user": unquote(datos.username or ""),
        "password": unquote(datos.password or ""),
        "dbname": (datos.path or "/").lstrip("/") or "postgres",
    }


def _pg_dump() -> str:
    """Ruta de pg_dump: variable de entorno, PATH o instalación típica."""
    elegido = os.environ.get("PG_DUMP")
    if elegido and Path(elegido).exists():
        return elegido
    encontrado = shutil.which("pg_dump")
    if encontrado:
        return encontrado
    for version in ("18", "17", "16", "15"):
        ruta = Path(rf"C:\Program Files\PostgreSQL\{version}\bin\pg_dump.exe")
        if ruta.exists():
            return str(ruta)
    raise SystemExit(
        "No se encontró pg_dump. Instalá el cliente de PostgreSQL o definí "
        "PG_DUMP con la ruta."
    )


def _pg_restore() -> str:
    return _pg_dump().replace("pg_dump", "pg_restore")


def _copy_database(source: Path, target: Path) -> None:
    """Copia con la API de SQLite: consistente aunque haya escrituras."""
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _dump_postgres(target: Path) -> tuple[Path, str]:
    """Volcado completo en formato personalizado (comprimido)."""
    partes = _partes_postgres()
    salida = target / f"{partes['dbname']}.dump"
    comando = [
        _pg_dump(),
        f"--host={partes['host']}",
        f"--port={partes['port']}",
        f"--username={partes['user']}",
        f"--dbname={partes['dbname']}",
        "--format=custom",
        "--compress=6",
        f"--file={salida}",
    ]
    entorno = {**os.environ, "PGPASSWORD": partes["password"]}
    resultado = subprocess.run(
        comando, capture_output=True, text=True, env=entorno, timeout=1800
    )
    if resultado.returncode != 0:
        raise SystemExit(f"pg_dump falló: {resultado.stderr[:400]}")
    # Verificación: el archivo tiene que ser legible por pg_restore.
    listado = subprocess.run(
        [_pg_restore(), "--list", str(salida)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if listado.returncode != 0:
        raise SystemExit(f"La copia no se puede leer: {listado.stderr[:300]}")
    tablas = sum(
        1 for linea in listado.stdout.splitlines() if " TABLE DATA " in linea
    )
    return salida, f"{tablas} tablas con datos"


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


def _rotar(backup_dir: Path, keep: int) -> tuple[int, int]:
    backups = sorted(
        (path for path in backup_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    removed = 0
    for old in backups[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
        removed += 1
    return min(len(backups), keep), removed


def run(
    backup_dir: Path,
    *,
    keep: int = 14,
    root: Path | None = None,
    source: Path | None = None,
) -> dict:
    root = root or Path(__file__).resolve().parent.parent
    es_sqlite = _url().startswith(SQLITE)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / stamp
    target.mkdir(parents=True, exist_ok=True)

    if es_sqlite:
        origen = source or _db_path()
        if not origen.exists():
            raise SystemExit(f"No existe la base {origen}")
        _copy_database(origen, target / origen.name)
        conn = sqlite3.connect(target / origen.name)
        try:
            resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if resultado != "ok":
            raise SystemExit(f"La copia falló la verificación: {resultado}")
        archivo = target / origen.name
        detalle = "integrity ok"
    else:
        archivo, detalle = _dump_postgres(target)
        resultado = "ok"

    env = root / ".env"
    if env.exists():
        shutil.copy2(env, target / ".env")
    _copy_tree(root / "knowledge", target / "knowledge")

    kept, removed = _rotar(backup_dir, keep)
    size_mb = round(archivo.stat().st_size / 1024 / 1024, 1)
    logger.info(
        "Backup %s (%s MB, %s). Conservadas: %s. Borradas: %s",
        target.name,
        size_mb,
        detalle,
        kept,
        removed,
    )
    return {
        "path": str(target),
        "file": archivo.name,
        "size_mb": size_mb,
        "kept": kept,
        "removed": removed,
        "integrity": resultado,
        "detalle": detalle,
    }


def verificar(carpeta: Path) -> int:
    """Comprueba que una copia se pueda leer."""
    dumps = list(carpeta.glob("*.dump"))
    if dumps:
        listado = subprocess.run(
            [_pg_restore(), "--list", str(dumps[0])],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if listado.returncode != 0:
            print("FALLA: el volcado no se puede leer")
            return 1
        print(f"OK: {dumps[0].name} legible por pg_restore")
        return 0
    bases = list(carpeta.glob("*.db"))
    if not bases:
        print("No hay base en esa carpeta")
        return 1
    conn = sqlite3.connect(bases[0])
    try:
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    print(f"{'OK' if resultado == 'ok' else 'FALLA'}: {bases[0].name}")
    return 0 if resultado == "ok" else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="backups")
    parser.add_argument("--keep", type=int, default=14)
    parser.add_argument(
        "--verificar",
        default="",
        help="Carpeta de una copia para comprobar que se puede leer.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if args.verificar:
        raise SystemExit(verificar(Path(args.verificar).resolve()))
    result = run(Path(args.dir).resolve(), keep=args.keep)
    print(result)


if __name__ == "__main__":
    main()
