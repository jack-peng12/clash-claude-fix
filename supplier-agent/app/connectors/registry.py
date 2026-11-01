from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import ChannelAccount, utcnow
from ..security import decrypt_json
from .base import AuthExpired, Connector
from .email_conn import EmailConnector
from .platforms import (
    DiscordConnector,
    FacebookConnector,
    LinkedInConnector,
    RedditConnector,
    TelegramBotConnector,
    WhatsAppConnector,
)

CONNECTORS: dict[str, type[Connector]] = {c.platform: c for c in [
    EmailConnector, TelegramBotConnector, FacebookConnector, LinkedInConnector, RedditConnector,
    WhatsAppConnector, DiscordConnector,
]}


def build(acc: ChannelAccount) -> Connector:
    return CONNECTORS[acc.platform](decrypt_json(acc.config_enc))


def default_account(db: Session, platform: str) -> ChannelAccount | None:
    q = db.query(ChannelAccount).filter(ChannelAccount.platform == platform, ChannelAccount.status != "disabled")
    return q.filter(ChannelAccount.is_default.is_(True)).first() or q.first()


def verify_account(db: Session, acc: ChannelAccount) -> tuple[bool, str]:
    from ..services.logs import notify

    acc.last_check_at = utcnow()
    try:
        msg = build(acc).verify()
        acc.status, acc.last_error = "active", ""
        return True, msg
    except AuthExpired as e:
        acc.status, acc.last_error = "expired", str(e)
        notify(db, f"账号授权失效：{acc.name}", f"{e}。请在“账号管理”重新授权。", "/accounts", "error")
        return False, str(e)
    except Exception as e:
        acc.status, acc.last_error = "error", f"{type(e).__name__}: {e}"
        return False, acc.last_error
