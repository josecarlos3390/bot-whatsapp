"""Backup diario: copia consistente, retención y verificación."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import backup_db


def _make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("create table if not exists demo (id integer primary key, name text)")
    conn.executemany(
        "insert into demo (name) values (?)", [(f"item {i}",) for i in range(rows)]
    )
    conn.commit()
    conn.close()


def test_backup_copia_y_verifica(tmp_path):
    source = tmp_path / "dev.db"
    _make_db(source)
    root = tmp_path / "proyecto"
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge" / "envios.md").write_text("politica", encoding="utf-8")
    (root / ".env").write_text("PUBLIC_BASE_URL=x\n", encoding="utf-8")

    result = backup_db.run(tmp_path / "backups", root=root, source=source)

    assert result["integrity"] == "ok"
    copied = Path(result["path"])
    assert (copied / "dev.db").exists()
    assert (copied / ".env").exists()
    assert (copied / "knowledge" / "envios.md").exists()

    conn = sqlite3.connect(copied / "dev.db")
    try:
        assert conn.execute("select count(*) from demo").fetchone()[0] == 3
    finally:
        conn.close()


def test_backup_rota_las_viejas(tmp_path):
    source = tmp_path / "dev.db"
    _make_db(source)
    backups = tmp_path / "backups"
    backups.mkdir()
    for name in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (backups / name).mkdir()

    result = backup_db.run(backups, keep=2, root=tmp_path, source=source)

    restantes = sorted(path.name for path in backups.iterdir() if path.is_dir())
    assert len(restantes) == 2
    assert result["removed"] >= 1
