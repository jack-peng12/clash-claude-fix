"""Runtime settings stored in the database and editable from the admin UI."""

from sqlalchemy.orm import Session

from ..models import Setting

DEFAULTS: dict = {
    # Master switch for any outbound message on any channel.
    "outbound_enabled": True,
    # Sandbox: every outbound email is delivered to sandbox_address instead of the supplier.
    "sandbox_mode": True,
    "sandbox_address": "sandbox@localhost",
    "daily_send_limit": 50,
    "min_hours_between_messages": 24,
    "sender_name": "Procurement Team",
    "company_name": "Our Company",
    "company_signature": "Best regards,\nProcurement Team",
    "notify_emails": "",
    "inbox_poll_minutes": 5,
    "followup_check_minutes": 60,
    "llm_enabled": False,
    "llm_base_url": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "llm_price_in_per_1k": 0.00015,
    "llm_price_out_per_1k": 0.0006,
    "budget_daily_usd": 2.0,
    "budget_monthly_usd": 30.0,
    "budget_warn_ratio": 0.8,
    "search_max_queries_per_round": 6,
    "search_results_per_query": 10,
    "max_new_suppliers_per_round": 15,
    "pages_per_site": 4,
    "continuous_interval_hours": 24,
    "search_region": "wt-wt",
}

SECRET_KEYS = {"llm_api_key"}


def get(db: Session, key: str, default=None):
    row = db.get(Setting, key)
    if row is not None:
        return row.value
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default


def set_(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def all_settings(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(Setting).all():
        out[row.key] = row.value
    return out


def get_secret(db: Session, key: str) -> str:
    from ..security import decrypt_json

    raw = get(db, key)
    if not raw:
        return ""
    return decrypt_json(raw).get("v", "")


def set_secret(db: Session, key: str, value: str) -> None:
    from ..security import encrypt_json

    set_(db, key, encrypt_json({"v": value}) if value else "")
