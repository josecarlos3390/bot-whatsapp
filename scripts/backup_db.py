"""Copia de seguridad diaria de la base y la configuración.

Crea una carpeta por día con:
- una copia consistente de la base SQLite (api de backup, no copia de archivo),
- .env (credenciales y configuración),
- la carpeta knowledge/ (políticas y FAQ).

Conserva las últimas N copias y borra las más viejas.

Uso:
    python -m scripts.backup_db
    python -m scripts.backup_db --keep 30 --dir D:\\backups
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("backup")


def _db_path() -> Path:
    from app.config import settings

    url = settings.database_url
    if not url.startswith("sqlite"):
        raise SystemExit(
            "Este backup es para SQLite. Con Postgres usá pg_dump."
        )
    # sqlite+aiosqlite:///./dev.db
    raw = url.split("///", 1)[-1]
    return Path(raw).resolve()


def _copy_database(source: Path, target: Path) -> None:
    """Copia con la API de SQLite: queda consistente aunque haya escrituras."""
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


def run(
    backup_dir: Path,
    *,
    keep: int = 14,
    root: Path | None = None,
    source: Path | None = None,
) -> dict:
    root = root or Path(__file__).resolve().parent.parent
    source = source or _db_path()
    if not source.exists():
        raise SystemExit(f"No existe la base {source}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / stamp
    target.mkdir(parents=True, exist_ok=True)

    _copy_database(source, target / source.name)
    env = root / ".env"
    if env.exists():
        shutil.copy2(env, target / ".env")
    _copy_tree(root / "knowledge", target / "knowledge")

    # Verificación rápida: la copia debe abrir y pasar el chequeo de integridad.
    conn = sqlite3.connect(target / source.name)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if result != "ok":
        raise SystemExit(f"La copia falló la verificación: {result}")

    removed = 0
    backups = sorted(
        (path for path in backup_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    for old in backups[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
        removed += 1

    size_mb = round((target / source.name).stat().st_size / 1024 / 1024, 1)
    logger.info(
        "Backup %s (%s MB). Conservadas: %s. Borradas: %s",
        target.name,
        size_mb,
        min(len(backups), keep),
        removed,
    )
    return {
        "path": str(target),
        "size_mb": size_mb,
        "kept": min(len(backups), keep),
        "removed": removed,
        "integrity": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="backups")
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    result = run(Path(args.dir).resolve(), keep=args.keep)
    print(result)


if __name__ == "__main__":
    main()
