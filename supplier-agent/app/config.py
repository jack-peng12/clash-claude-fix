import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("SA_DATA_DIR", BASE_DIR.parent / "data")).resolve()
EVIDENCE_DIR = DATA_DIR / "evidence"
BACKUP_DIR = DATA_DIR / "backups"
DB_URL = os.environ.get("SA_DB_URL", f"sqlite:///{DATA_DIR / 'supplier_agent.db'}")

RUN_WORKER = _bool("SA_RUN_WORKER", True)
WORKER_POLL_SECONDS = float(os.environ.get("SA_WORKER_POLL_SECONDS", "3"))

# Bootstrap admin, only used when the users table is empty.
ADMIN_USERNAME = os.environ.get("SA_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("SA_ADMIN_PASSWORD", "admin123")

HTTP_USER_AGENT = os.environ.get(
    "SA_HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 SupplierResearchAgent/0.1",
)


def ensure_dirs() -> None:
    for d in (DATA_DIR, EVIDENCE_DIR, BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
