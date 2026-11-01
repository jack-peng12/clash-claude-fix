"""Deterministic business-rule functions. All behaviour is driven by skill content dicts."""

from __future__ import annotations

import re

CURRENCY_MAP = {
    "£": "GBP", "€": "EUR", "$": "USD", "us$": "USD", "gbp": "GBP", "eur": "EUR", "usd": "USD",
    "czk": "CZK", "kč": "CZK", "chf": "CHF", "aed": "AED", "egp": "EGP", "pln": "PLN", "zł": "PLN",
    "hkd": "HKD", "sgd": "SGD", "cad": "CAD", "aud": "AUD", "euro": "EUR", "euros": "EUR",
}
_CUR = r"(us\$|£|€|\$|gbp|eur|usd|czk|kč|chf|aed|egp|pln|zł|hkd|sgd|cad|aud|euros?)"
_NUM = r"(\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_PRICE_RE = re.compile(
    rf"(?:{_CUR}\s?{_NUM}(?!\s?%))|(?:{_NUM}\s?{_CUR}(?![a-z]))", re.IGNORECASE
)
_YEAR_RE = re.compile(r"(?:incorporated|established|formed|founded|registered|since|gegründet|costituita|constituida)"
                      r"\D{0,30}((?:19|20)\d{2})", re.IGNORECASE)


def snippet(text: str, start: int, end: int, width: int = 120) -> str:
    s = max(0, start - width)
    e = min(len(text), end + width)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def parse_amount(raw: str) -> float | None:
    raw = raw.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+([.,]\d{1,2})?", raw):
        m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)([.,]\d{1,2})?", raw)
        whole = re.sub(r"[.,]", "", m.group(1))
        dec = (m.group(2) or "").replace(",", ".")
        try:
            return float(whole + dec)
        except ValueError:
            return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def find_prices(text: str, min_amount: float = 50) -> list[dict]:
    out = []
    for m in _PRICE_RE.finditer(text):
        cur = (m.group(1) or m.group(4) or "").lower()
        num = m.group(2) or m.group(3)
        amount = parse_amount(num or "")
        if amount is None or amount < min_amount or amount > 10_000_000:
            continue
        out.append({"amount": amount, "currency": CURRENCY_MAP.get(cur, cur.upper()),
                    "snippet": snippet(text, m.start(), m.end(), 80)})
    return out


def find_incorporation_years(text: str) -> list[int]:
    return sorted({int(m.group(1)) for m in _YEAR_RE.finditer(text)})


def strip_quoted(body: str) -> str:
    """Remove quoted previous messages from an email reply."""
    lines = []
    for line in body.splitlines():
        ls = line.strip()
        if re.match(r"^on .{0,200} wrote:$", ls, re.IGNORECASE) or ls.startswith("-----Original Message"):
            break
        if re.match(r"^(from|von|de):\s", ls, re.IGNORECASE) and lines:
            break
        if ls.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _find_any(low: str, patterns: list[str]) -> tuple[int, int] | None:
    for p in patterns:
        p = p.lower()
        if not p:
            continue
        i = low.find(p)
        if i >= 0:
            return i, i + len(p)
    return None


def detect_criteria(text: str, criteria: list[dict]) -> dict[str, dict]:
    """Return {key: {polarity: yes/no, snippet}} for criteria mentioned in text. Negatives win."""
    low = text.lower()
    found: dict[str, dict] = {}
    for c in criteria:
        key = c["key"]
        neg = _find_any(low, c.get("negative", []))
        if neg:
            found[key] = {"polarity": "no", "snippet": snippet(text, *neg)}
            continue
        pos = _find_any(low, c.get("positive", []))
        if pos:
            found[key] = {"polarity": "yes", "snippet": snippet(text, *pos)}
    prices = find_prices(text)
    if prices:
        found["price"] = {"polarity": "yes", "snippet": prices[0]["snippet"], "prices": prices}
    years = find_incorporation_years(text)
    if years:
        found["incorporation_age"] = {"polarity": "yes", "snippet": f"成立年份: {', '.join(map(str, years))}",
                                      "years": years}
    return found


def detect_risk(text: str, risk_rules: list[dict]) -> dict:
    low = text.lower()
    hits = [r for r in risk_rules if r["pattern"].lower() in low]
    level = "low"
    if any(h["level"] == "high" for h in hits):
        level = "high"
    elif hits:
        level = "medium"
    return {"level": level, "hits": [{"pattern": h["pattern"], "reason": h["reason"], "level": h["level"]} for h in hits]}


def is_blocked(url: str, search_rules: dict) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == b or host.endswith("." + b) for b in search_rules.get("blocklist", []))


def is_relevant(url: str, text: str, search_rules: dict) -> tuple[bool, int]:
    if is_blocked(url, search_rules):
        return False, 0
    low = text.lower()
    hits = sum(1 for k in search_rules.get("relevance_keywords", []) if k.lower() in low)
    return hits >= search_rules.get("min_relevance_hits", 1), hits


def screen(relevant: bool, levels: dict[str, str], facts: dict[str, str], risk: str, rules: dict) -> dict:
    """facts: {criterion_key: 'yes'|'no'|'unknown'}"""
    weights = rules.get("weights", {"required": 3, "preferred": 1})
    labels = {c["key"]: c["label"] for c in rules.get("criteria", [])}
    detail, missing, failed = [], [], []
    total = got = 0.0
    for key, level in levels.items():
        if level == "not_required":
            continue
        w = weights.get(level, 0)
        pol = facts.get(key, "unknown")
        if level in ("required", "preferred"):
            total += w
            if pol == "yes":
                got += w
        if pol == "no" and level == "required":
            failed.append(key)
        if pol == "unknown" and level in ("required", "to_confirm"):
            missing.append(key)
        detail.append({"key": key, "label": labels.get(key, key), "level": level, "status": pol})

    score = round(100 * got / total, 1) if total else (50.0 if relevant else 0.0)
    if not relevant:
        category, reason = "no_match", "网站未显示现成公司/公司注册相关业务"
    elif risk == "high":
        category, reason = "high_risk", "命中高风险规则"
    elif failed:
        category, reason = "no_match", "必须条件不满足: " + ", ".join(labels.get(k, k) for k in failed)
    elif any(levels.get(k) == "required" for k in missing):
        category, reason = "insufficient", "缺少证据: " + ", ".join(labels.get(k, k) for k in missing)
    else:
        category, reason = "match", "所有必须条件均有正向证据（未经人工核验）"
    return {"category": category, "score": score, "reason": reason, "detail": detail,
            "missing": missing, "failed": failed}


def check_forbidden(text: str, phrases: list[str]) -> list[str]:
    low = text.lower()
    return [p for p in phrases if p.lower() in low]


def is_opt_out(text: str, patterns: list[str]) -> bool:
    low = strip_quoted(text).lower()
    return any(p.lower() in low for p in patterns)


def answered_keys(reply: str, criteria: list[dict]) -> dict[str, dict]:
    return detect_criteria(strip_quoted(reply), criteria)


def next_questions(levels: dict[str, str], qstate: dict[str, dict], rules: dict, order: list[str] | None = None,
                   limit: int | None = None) -> list[str]:
    """qstate: {key: {asked_count, answered}}. Returns criterion keys to ask next."""
    max_asks = rules.get("max_asks_per_question", 2)
    limit = limit or rules.get("max_questions_per_message", 3)
    ask_levels = rules.get("ask_levels", ["required", "to_confirm", "preferred"])
    candidates = []
    for lvl in ask_levels:
        for key, l in levels.items():
            if l != lvl:
                continue
            st = qstate.get(key, {})
            if st.get("answered") or st.get("asked_count", 0) >= max_asks:
                continue
            candidates.append(key)
    if order:
        rank = {k: i for i, k in enumerate(order)}
        candidates.sort(key=lambda k: (ask_levels.index(levels[k]) if levels[k] in ask_levels else 9,
                                       rank.get(k, 99)))
    seen, out = set(), []
    for k in candidates:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out[:limit]


def compute_intent(reply: str, rules: dict, criteria: list[dict], required_keys: list[str],
                   opt_out_patterns: list[str], extra_signals: list[str] | None = None) -> dict:
    text = strip_quoted(reply)
    low = text.lower()
    if is_opt_out(text, opt_out_patterns):
        return {"score": 0, "level": "none", "signals": [], "handoff": False, "refusal": True,
                "reason": "供应商拒绝或要求停止联系"}
    detected = detect_criteria(text, criteria)
    inventory_negative = detected.get("inventory", {}).get("polarity") == "no"
    signals, score = [], 0.0
    cap = rules.get("single_keyword_cap", 15)
    for sig in rules.get("signals", []):
        hit = False
        for p in sig["patterns"]:
            if p == "__PRICE__":
                hit = bool(detected.get("price"))
            elif p == "__CRITERIA_MET__":
                hit = bool(required_keys) and any(detected.get(k, {}).get("polarity") == "yes" for k in required_keys)
            elif re.search(r"(?<![a-z])" + re.escape(p.lower()) + r"(?![a-z])", low):
                hit = True
            if hit:
                break
        if sig["key"] == "has_inventory" and inventory_negative:
            hit = False
        if extra_signals and sig["key"] in extra_signals:
            hit = True
        if hit:
            w = sig["weight"]
            if len(sig["patterns"]) > 0 and sig["patterns"][0] not in ("__PRICE__", "__CRITERIA_MET__"):
                w = min(w, cap) if sig["key"] == "next_steps" else w
            score += w
            signals.append(sig["key"])
    score = min(100.0, score)
    lv = rules.get("levels", {"high": 60, "medium": 35, "low": 10})
    level = "high" if score >= lv["high"] else "medium" if score >= lv["medium"] else "low" if score >= lv["low"] else "none"
    combo = next((c for c in rules.get("hard_combos", []) if all(s in signals for s in c)), None)
    handoff = score >= rules.get("handoff_threshold", 60) or combo is not None
    reason = (f"命中组合条件 {'+'.join(combo)}" if combo else f"意向分 {score:.0f}") if handoff else ""
    return {"score": score, "level": "high" if handoff else level, "signals": signals, "handoff": handoff,
            "refusal": False, "reason": reason, "detected": detected}


def followup_decision(state: dict, rules: dict) -> dict:
    if state.get("status") in rules.get("stop_statuses", []):
        return {"action": "stop", "reason": f"状态为 {state.get('status')}"}
    if state.get("replied_after"):
        return {"action": "wait", "reason": "供应商已回复，等待处理"}
    n = state.get("followups", 0)
    sched = rules.get("schedule_days", [3, 7, 14])
    if n >= rules.get("max_followups", len(sched)):
        return {"action": "stop", "reason": "已达最大跟进次数"}
    due = sched[min(n, len(sched) - 1)]
    if state.get("days_since_out", 0) >= due:
        return {"action": "followup", "reason": f"已 {state.get('days_since_out'):.0f} 天未回复（阈值 {due} 天）"}
    return {"action": "wait", "reason": f"未到跟进时间（阈值 {due} 天）"}


def due_diligence(fact_status: dict[str, str], rules: dict, criteria: list[dict]) -> list[dict]:
    always = {c["key"] for c in criteria if c.get("always_human_verify")}
    verified = set(rules.get("verified_statuses", ["human_verified"]))
    docs = rules.get("documents", {})
    out = []
    for key, st in fact_status.items():
        if st in verified and key not in always:
            continue
        if st in verified and key in always:
            continue
        out.append({"key": key, "status": st, "documents": docs.get(key, "相关证明文件"),
                    "human_only": key in always})
    return out
