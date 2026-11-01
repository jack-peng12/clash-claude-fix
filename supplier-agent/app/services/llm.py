"""Optional OpenAI-compatible LLM client with budget enforcement and cost logging.

Works with OpenAI, DeepSeek, Qwen (DashScope compatible mode), Moonshot, local Ollama, etc.
Every caller has a deterministic rule-based fallback, so returning None is always safe.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import CostRecord, utcnow
from . import settings
from .logs import notify, syslog


def _spent_since(db: Session, since: datetime) -> float:
    return float(db.query(func.coalesce(func.sum(CostRecord.cost_usd), 0)).filter(CostRecord.created_at >= since).scalar())


def budget_status(db: Session) -> dict:
    now = utcnow()
    day = _spent_since(db, now.replace(hour=0, minute=0, second=0, microsecond=0))
    month = _spent_since(db, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    dl = float(settings.get(db, "budget_daily_usd"))
    ml = float(settings.get(db, "budget_monthly_usd"))
    return {"day": day, "month": month, "daily_limit": dl, "monthly_limit": ml,
            "exceeded": day >= dl or month >= ml,
            "warn": day >= dl * float(settings.get(db, "budget_warn_ratio")) or
            month >= ml * float(settings.get(db, "budget_warn_ratio"))}


def _config(db: Session) -> dict | None:
    key = os.environ.get("SA_LLM_API_KEY") or settings.get_secret(db, "llm_api_key")
    enabled = settings.get(db, "llm_enabled") or bool(os.environ.get("SA_LLM_API_KEY"))
    if not enabled or not key:
        return None
    return {"key": key,
            "base_url": os.environ.get("SA_LLM_BASE_URL") or settings.get(db, "llm_base_url"),
            "model": os.environ.get("SA_LLM_MODEL") or settings.get(db, "llm_model")}


def available(db: Session) -> bool:
    return _config(db) is not None


def chat(db: Session, purpose: str, system: str, user: str, task_id: int | None = None,
         json_mode: bool = False, max_tokens: int = 1200) -> str | None:
    cfg = _config(db)
    if cfg is None:
        return None
    b = budget_status(db)
    if b["exceeded"]:
        _warn_once(db, "LLM 预算已用尽", f"今日 ${b['day']:.3f} / 本月 ${b['month']:.3f}，已自动切换为规则模式。")
        return None
    payload = {"model": cfg["model"], "messages": [{"role": "system", "content": system},
                                                   {"role": "user", "content": user[:24000]}],
               "temperature": 0.2, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(cfg["base_url"].rstrip("/") + "/chat/completions", json=payload,
                       headers={"Authorization": f"Bearer {cfg['key']}"}, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        syslog("ERROR", "llm", f"{purpose} 调用失败: {e}")
        return None
    usage = data.get("usage") or {}
    pin, pout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
    cost = pin / 1000 * float(settings.get(db, "llm_price_in_per_1k")) + pout / 1000 * float(
        settings.get(db, "llm_price_out_per_1k"))
    db.add(CostRecord(provider="llm", model=cfg["model"], purpose=purpose, units_in=pin, units_out=pout,
                      cost_usd=cost, task_id=task_id))
    db.flush()
    if budget_status(db)["warn"]:
        _warn_once(db, "LLM 费用接近预算上限", "请在“成本统计”查看并调整预算。")
    return data["choices"][0]["message"]["content"]


def chat_json(db: Session, purpose: str, system: str, user: str, task_id: int | None = None) -> dict | None:
    txt = chat(db, purpose, system, user, task_id=task_id, json_mode=True)
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        return json.loads(m.group(0) if m else txt)
    except (ValueError, AttributeError):
        syslog("WARNING", "llm", f"{purpose} 返回非JSON: {txt[:300]}")
        return None


_last_warn: dict[str, datetime] = {}


def _warn_once(db: Session, title: str, body: str) -> None:
    now = utcnow()
    if title in _last_warn and now - _last_warn[title] < timedelta(hours=6):
        return
    _last_warn[title] = now
    notify(db, title, body, "/costs", "warning")


def translate_zh(db: Session, text: str, task_id: int | None = None) -> str:
    out = chat(db, "translate", "把以下商务邮件翻译成简体中文，保留金额和专有名词。只输出译文。", text,
               task_id=task_id, max_tokens=1500)
    return out or ""
