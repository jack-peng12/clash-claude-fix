"""Multilingual search query generation, with adaptation from previous search yield."""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy.orm import Session

from . import llm
from ..models import SearchRun

_STOP = {"the", "and", "for", "with", "a", "of", "in", "to", "your", "our", "buy", "sale", "best", "top",
         "ltd", "limited", "uk", "com", "co", "company", "companies", "|", "-", "–", "&", "on", "at", "by"}


def template_queries(spec: dict, rules: dict, used: set[str]) -> list[dict]:
    templates = rules.get("templates", {})
    ctypes = spec.get("company_types") or [""]
    out: list[dict] = []
    for c in spec.get("countries", []):
        for lang in c.get("langs", ["en"]):
            for t in templates.get(lang, []):
                for ct in ctypes:
                    q = t.format(country=c["name"], country_local=c.get("local", c["name"]), ctype=ct)
                    q = re.sub(r"\s+", " ", q).strip()
                    if q.lower() not in used and q.lower() not in {x["query"].lower() for x in out}:
                        out.append({"query": q, "lang": lang, "origin": "template"})
                    if "{ctype}" not in t:
                        break
    return out


def adaptive_queries(db: Session, task_id: int, spec: dict, rules: dict, used: set[str]) -> list[dict]:
    """Mine frequent phrases from titles of relevant results and turn them into new queries."""
    runs = db.query(SearchRun).filter_by(task_id=task_id).all()
    counter: Counter = Counter()
    for r in runs:
        for res in r.results or []:
            if not res.get("relevant"):
                continue
            words = [w for w in re.findall(r"[a-zA-ZÀ-ž\-]{3,}", (res.get("title") or "").lower()) if w not in _STOP]
            for a, b in zip(words, words[1:]):
                counter[f"{a} {b}"] += 1
    out = []
    min_freq = rules.get("adaptive_min_term_freq", 2)
    for phrase, n in counter.most_common(10):
        if n < min_freq:
            break
        for c in spec.get("countries", [])[:3]:
            q = f"{phrase} {c['name']}"
            if q.lower() not in used:
                out.append({"query": q, "lang": "en", "origin": "adaptive"})
    return out


def llm_queries(db: Session, task_id: int, spec: dict, used: set[str], yields: list[tuple[str, int]]) -> list[dict]:
    data = llm.chat_json(
        db, "generate_queries",
        "You generate web search queries to find businesses that SELL ready-made/shelf companies "
        "(company formation agents, corporate service providers). Output JSON only.",
        f"Target: {spec}\nAlready used queries with number of new suppliers found: {yields[:30]}\n"
        "Propose 6 NEW queries in English and the local languages of the target countries. "
        'Format: {"queries": [{"query": "...", "lang": "xx"}]}',
        task_id=task_id,
    )
    out = []
    for q in (data or {}).get("queries", []):
        if isinstance(q, dict) and q.get("query") and q["query"].lower() not in used:
            out.append({"query": q["query"][:200], "lang": q.get("lang", "en")[:8], "origin": "llm"})
    return out


def next_queries(db: Session, task_id: int, spec: dict, rules: dict, limit: int) -> list[dict]:
    runs = db.query(SearchRun).filter_by(task_id=task_id).all()
    used = {r.query.lower() for r in runs if r.status in ("done", "running")}
    yields = sorted(((r.query, r.new_suppliers) for r in runs), key=lambda x: -x[1])
    pool = template_queries(spec, rules, used)
    # Interleave languages so each round covers English and local languages.
    by_lang: dict[str, list] = {}
    for q in pool:
        by_lang.setdefault(q["lang"], []).append(q)
    interleaved = []
    while any(by_lang.values()):
        for lang in list(by_lang):
            if by_lang[lang]:
                interleaved.append(by_lang[lang].pop(0))
    adaptive = adaptive_queries(db, task_id, spec, rules, used)
    llmq = llm_queries(db, task_id, spec, used, yields) if runs else []
    chosen: list[dict] = []
    # Once templates are partly used, give adaptive/LLM queries priority slots.
    if runs:
        chosen += (llmq[:2] + adaptive[:2])
    for q in interleaved + adaptive + llmq:
        if len(chosen) >= limit:
            break
        if q["query"].lower() not in {c["query"].lower() for c in chosen}:
            chosen.append(q)
    return chosen[:limit]
