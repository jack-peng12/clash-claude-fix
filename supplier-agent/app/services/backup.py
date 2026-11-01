"""Consistent SQLite backup (online backup API) + evidence/keys archived into one zip."""

from __future__ import annotations

import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config

KEEP = 14


def _db_path() -> Path:
    return Path(config.DB_URL.replace("sqlite:///", ""))


def create_backup() -> str:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_db = config.BACKUP_DIR / f"db_{stamp}.sqlite"
    src = sqlite3.connect(_db_path())
    dst = sqlite3.connect(tmp_db)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    out = config.BACKUP_DIR / f"backup_{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "supplier_agent.db")
        for key in ("secret.key", "session.key"):
            if (config.DATA_DIR / key).exists():
                z.write(config.DATA_DIR / key, key)
        for f in config.EVIDENCE_DIR.rglob("*"):
            if f.is_file():
                z.write(f, str(f.relative_to(config.DATA_DIR)))
    tmp_db.unlink()
    backups = sorted(config.BACKUP_DIR.glob("backup_*.zip"))
    for old in backups[:-KEEP]:
        old.unlink()
    return str(out)


def restore_backup(zip_path: str) -> None:
    """Restore into DATA_DIR. The application must be stopped (scripts handle this)."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "supplier_agent.db" not in names:
            raise ValueError("不是有效的备份文件")
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(_db_path()) + suffix)
            if p.exists():
                p.unlink()
        z.extractall(config.DATA_DIR)
    extracted = config.DATA_DIR / "supplier_agent.db"
    if extracted != _db_path():
        extracted.replace(_db_path())


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "restore":
        restore_backup(sys.argv[2])
        print("restored", sys.argv[2])
    else:
        print(create_backup())
