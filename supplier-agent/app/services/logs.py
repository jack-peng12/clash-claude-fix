import logging

from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import AuditLog, Notification, SystemLog

logger = logging.getLogger("supplier_agent")


def audit(db: Session, actor: str, action: str, target: str = "", detail: str = "") -> None:
    db.add(AuditLog(actor=actor, action=action, target=target, detail=detail[:4000]))


def syslog(level: str, source: str, message: str) -> None:
    getattr(logger, level.lower(), logger.info)(f"[{source}] {message}")
    try:
        with session_scope() as s:
            s.add(SystemLog(level=level.upper(), source=source, message=message[:8000]))
    except Exception:  # logging must never break the caller
        logger.exception("failed to persist system log")


def notify(db: Session, title: str, body: str = "", link: str = "", level: str = "info") -> None:
    db.add(Notification(title=title, body=body, link=link, level=level))
