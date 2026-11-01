"""Chinese natural-language procurement requirement -> structured task spec."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from . import llm
from .countries import COMPANY_TYPES, COUNTRIES, find_by_name, to_dict

_PREFER = ["最好", "优先", "如果有", "加分", "尽量", "可选"]
_CONFIRM = ["待确认", "需确认", "问一下", "了解一下", "确认是否"]
_NOT_REQ = ["不要求", "无所谓", "不需要", "可有可无"]


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[，,。；;、\n]|并且|而且|同时|另外", text) if c.strip()]


def _level_for(clause: str) -> str:
    if any(k in clause for k in _NOT_REQ):
        return "not_required"
    if any(k in clause for k in _CONFIRM):
        return "to_confirm"
    if any(k in clause for k in _PREFER):
        return "preferred"
    return "required"


def parse_rules(text: str, criteria: list[dict]) -> dict:
    countries = []
    low = text.lower()
    for zh, en, iso, langs, local, tld in COUNTRIES:
        if any(z in text for z in zh) or re.search(rf"\b{re.escape(en.lower())}\b", low):
            countries.append(to_dict(zh, en, iso, langs, local, tld))
    ctypes = [t for t in COMPANY_TYPES if re.search(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", text)]

    levels: dict[str, str] = {"inventory": "required"}
    params: dict = {}
    for clause in _clauses(text):
        cl = clause.lower()
        for c in criteria:
            if c["key"] in ("inventory",):
                continue
            if any(k.lower() in cl for k in c.get("zh_keywords", [])):
                lvl = _level_for(clause)
                # Never downgrade a criterion already marked required by an earlier clause.
                if levels.get(c["key"]) != "required" or lvl == "not_required":
                    levels[c["key"]] = lvl
        m = re.search(r"成立\s*(\d+)\s*年", clause) or re.search(r"(\d+)\s*年以上", clause)
        if m:
            params["min_age_years"] = int(m.group(1))
            levels["incorporation_age"] = _level_for(clause)
        m = re.search(r"(预算|价格|报价)[^\d]{0,8}(\d[\d,，.]*)\s*(万)?\s*(欧元|英镑|美元|人民币|eur|gbp|usd|rmb)?",
                      clause, re.IGNORECASE)
        if m:
            amt = float(m.group(2).replace(",", "").replace("，", ""))
            if m.group(3):
                amt *= 10000
            params["max_price"] = amt
            params["currency"] = {"欧元": "EUR", "英镑": "GBP", "美元": "USD", "人民币": "CNY"}.get(
                m.group(4) or "", (m.group(4) or "").upper())
            levels.setdefault("price", "required")
    levels.setdefault("price", "required")
    m = re.search(r"(\d+)\s*(家|个)", text)
    target = int(m.group(1)) if m and int(m.group(1)) < 1000 else 20
    return {"countries": countries, "company_types": ctypes, "levels": levels, "params": params,
            "target_suppliers": target, "notes": "", "parser": "rules"}


def parse(db: Session, text: str, criteria: list[dict], task_id: int | None = None) -> dict:
    spec = parse_rules(text, criteria)
    keys = [c["key"] for c in criteria]
    data = llm.chat_json(
        db, "parse_requirement",
        "你是跨境采购需求分析助手。把员工的中文采购需求转成JSON。只输出JSON，不要编造需求里没有的条件。",
        "可用条件key: " + ", ".join(keys) + "\n等级: required/preferred/not_required/to_confirm\n"
        "输出格式: {\"countries\": [英文国家名], \"company_types\": [], \"levels\": {key: 等级}, "
        "\"params\": {\"min_age_years\": 数字或null, \"max_price\": 数字或null, \"currency\": \"\"}, "
        "\"target_suppliers\": 数字, \"notes\": \"无法归类的要求\"}\n\n需求: " + text,
        task_id=task_id,
    )
    if data:
        llm_countries = [find_by_name(n) for n in data.get("countries", []) if isinstance(n, str)]
        llm_countries = [c for c in llm_countries if c]
        known = {c["iso"] for c in spec["countries"]}
        spec["countries"] += [c for c in llm_countries if c["iso"] not in known]
        for k, v in (data.get("levels") or {}).items():
            if k in keys and v in ("required", "preferred", "not_required", "to_confirm"):
                spec["levels"].setdefault(k, v)
        for k, v in (data.get("params") or {}).items():
            if v not in (None, "") and k not in spec["params"]:
                spec["params"][k] = v
        spec["company_types"] = sorted(set(spec["company_types"]) | set(data.get("company_types") or []))
        spec["notes"] = data.get("notes") or ""
        spec["parser"] = "rules+llm"
    return spec
