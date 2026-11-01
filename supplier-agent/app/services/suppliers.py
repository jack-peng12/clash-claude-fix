"""Supplier records: upsert/dedupe/merge, facts, screening, handoff and takeover."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (
    Contact,
    Evidence,
    Fact,
    Handoff,
    ManualAction,
    Message,
    ProcurementTask,
    Supplier,
    SupplierQuestion,
    SupplierTask,
    utcnow,
)
from ..skills import engine as skills
from . import rules as R
from .logs import audit, notify

STATUS_RANK = {"human_verified": 4, "doc_provided": 3, "supplier_claim": 2, "web_claim": 1, "unknown": 0}


def find_existing(db: Session, domain: str | None, contacts: list[dict]) -> Supplier | None:
    if domain:
        s = db.query(Supplier).filter_by(domain=domain).first()
        if s:
            return s
    for c in contacts:
        if c["ctype"] in ("email", "phone", "whatsapp", "telegram"):
            hit = db.query(Contact).filter_by(ctype=c["ctype"], normalized=c["normalized"]).first()
            if hit:
                return hit.supplier
    return None


def add_contacts(db: Session, sup: Supplier, contacts: list[dict], source_url: str, evidence_id: int | None) -> int:
    n = 0
    for c in contacts:
        existing = db.query(Contact).filter_by(ctype=c["ctype"], normalized=c["normalized"]).first()
        if existing:
            continue
        db.add(Contact(supplier_id=sup.id, ctype=c["ctype"], value=c["value"][:500], normalized=c["normalized"][:500],
                       source_url=source_url, evidence_id=evidence_id))
        db.flush()
        n += 1
    return n


def add_fact(db: Session, sup: Supplier, key: str, polarity: str, status: str, snippet: str,
             evidence_id: int | None = None, message_id: int | None = None, value: str = "",
             amount: float | None = None, currency: str = "") -> Fact | None:
    if status == "human_verified":
        raise ValueError("AI 不能写入人工核验状态")
    dup = db.query(Fact).filter_by(supplier_id=sup.id, key=key, polarity=polarity, status=status,
                                   snippet=snippet[:2000]).first()
    if dup:
        return None
    f = Fact(supplier_id=sup.id, key=key, polarity=polarity, status=status, snippet=snippet[:2000],
             evidence_id=evidence_id, message_id=message_id, value=value[:500], amount=amount, currency=currency)
    db.add(f)
    db.flush()
    return f


def fact_summary(db: Session, sup: Supplier) -> dict[str, dict]:
    """Best-evidenced polarity per criterion: higher evidence rank wins, newer wins on ties."""
    out: dict[str, dict] = {}
    for f in db.query(Fact).filter_by(supplier_id=sup.id).order_by(Fact.created_at.asc()).all():
        cur = out.get(f.key)
        if cur is None or STATUS_RANK.get(f.status, 0) >= STATUS_RANK.get(cur["status"], 0):
            out[f.key] = {"polarity": f.polarity, "status": f.status, "snippet": f.snippet, "fact_id": f.id}
    return out


def country_mentioned(text: str, domain: str, spec: dict) -> list[str]:
    low = text.lower()
    hits = []
    for c in spec.get("countries", []):
        names = {c["name"].lower(), c.get("local", "").lower()}
        if c["iso"] == "GB":
            names |= {"united kingdom", "england", "uk ", " uk", "companies house", "british"}
        if c["iso"] == "US":
            names |= {"usa", "delaware", "wyoming", "u.s.", "united states"}
        if any(n and n in low for n in names) or (domain or "").endswith("." + c.get("tld", "~")):
            hits.append(c["name"])
    return hits


def screen_supplier(db: Session, sup: Supplier, task: ProcurementTask, page_text: str = "") -> dict:
    rules = skills.get_rules(db, "screening")
    search_rules = skills.get_rules(db, "search")
    summary = fact_summary(db, sup)
    relevant = summary.get("inventory", {}).get("polarity") == "yes" or (
        R.is_relevant(sup.website, page_text or sup.description, search_rules)[0])
    risk = R.detect_risk(page_text or sup.description, skills.get_rules(db, "risk").get("patterns", []))
    if sup.risk_level == "high":
        risk["level"] = "high"
    levels = dict(task.spec.get("levels", {}))
    facts = {k: v["polarity"] for k, v in summary.items()}
    web_negatives = []
    if not rules.get("web_negative_is_fail", False):
        for k, v in summary.items():
            if v["polarity"] == "no" and v["status"] == "web_claim" and levels.get(k) == "required":
                facts[k] = "unknown"
                web_negatives.append(k)
    if task.spec.get("countries"):
        levels = {"country": "required", **levels}
        facts["country"] = "yes" if sup.country_hint else "unknown"
    res = R.screen(relevant, levels, facts, risk["level"], rules)
    for d in res["detail"]:
        if d["key"] == "country":
            d["label"] = "目标国家"
        st = summary.get(d["key"], {}).get("status")
        d["evidence_status"] = st or "unknown"
    if web_negatives:
        labels = {c["key"]: c["label"] for c in rules.get("criteria", [])}
        res["reason"] += "；网站有反向表述待供应商确认: " + ", ".join(labels.get(k, k) for k in web_negatives)
        for d in res["detail"]:
            if d["key"] in web_negatives:
                d["status"] = "no"
    res["risk"] = risk
    res["due_diligence"] = R.due_diligence({k: v["status"] for k, v in summary.items()},
                                           skills.get_rules(db, "due_diligence"), rules.get("criteria", []))
    sup.fit_category, sup.fit_score, sup.risk_level, sup.assessment = res["category"], res["score"], risk["level"], res
    link = db.query(SupplierTask).filter_by(supplier_id=sup.id, task_id=task.id).first()
    if link:
        link.fit_category, link.fit_score, link.assessment = res["category"], res["score"], res
    if sup.status == "new":
        sup.status = "screened"
    return res


def create_handoff(db: Session, sup: Supplier, reason: str, score: float, triggered: list, source: str = "ai",
                   actor: str = "ai") -> Handoff:
    open_h = db.query(Handoff).filter(Handoff.supplier_id == sup.id, Handoff.status.in_(["open", "accepted"])).first()
    sup.taken_over = True
    sup.taken_over_at = sup.taken_over_at or utcnow()
    sup.status = "human_takeover"
    sup.intent_level = "high" if source == "ai" else sup.intent_level
    from .messaging import cancel_pending_for_supplier

    cancel_pending_for_supplier(db, sup.id, "已转人工，取消AI待发消息")
    if open_h:
        return open_h
    h = Handoff(supplier_id=sup.id, reason=reason, score=score, triggered=triggered, source=source)
    db.add(h)
    db.flush()
    risk = f"（注意：风险等级 {sup.risk_level}）" if sup.risk_level in ("high", "medium") else ""
    notify(db, f"高意向供应商待接手：{sup.name or sup.domain}", f"{reason}{risk}", f"/suppliers/{sup.id}", "success")
    audit(db, actor, "handoff_created", f"supplier:{sup.id}", reason)
    return h


def accept_handoff(db: Session, h: Handoff, user_id: int, actor: str) -> None:
    h.status, h.assigned_to, h.accepted_at = "accepted", user_id, utcnow()
    sup = db.get(Supplier, h.supplier_id)
    sup.taken_over, sup.taken_over_by = True, user_id
    audit(db, actor, "handoff_accepted", f"supplier:{sup.id}")


def manual_takeover(db: Session, sup: Supplier, user_id: int, actor: str) -> Handoff:
    h = create_handoff(db, sup, "员工手动接管", sup.intent_score, [], source="manual", actor=actor)
    accept_handoff(db, h, user_id, actor)
    return h


def release_to_ai(db: Session, sup: Supplier, actor: str) -> None:
    sup.taken_over, sup.taken_over_by = False, None
    sup.status = "replied" if sup.last_inbound_at else "contacted" if sup.last_outbound_at else "screened"
    for h in db.query(Handoff).filter(Handoff.supplier_id == sup.id, Handoff.status.in_(["open", "accepted"])):
        h.status = "closed"
    audit(db, actor, "released_to_ai", f"supplier:{sup.id}")


def merge(db: Session, keep: Supplier, other: Supplier, actor: str) -> None:
    if keep.id == other.id:
        return
    for model in (Contact, Fact, Message, Evidence, Handoff, ManualAction):
        db.query(model).filter_by(supplier_id=other.id).update({"supplier_id": keep.id})
    for q in db.query(SupplierQuestion).filter_by(supplier_id=other.id).all():
        mine = db.query(SupplierQuestion).filter_by(supplier_id=keep.id, key=q.key).first()
        if mine:
            mine.asked_count = max(mine.asked_count, q.asked_count)
            mine.answered = mine.answered or q.answered
            db.delete(q)
        else:
            q.supplier_id = keep.id
    for st in db.query(SupplierTask).filter_by(supplier_id=other.id).all():
        if db.query(SupplierTask).filter_by(supplier_id=keep.id, task_id=st.task_id).first():
            db.delete(st)
        else:
            st.supplier_id = keep.id
    keep.opted_out = keep.opted_out or other.opted_out
    keep.taken_over = keep.taken_over or other.taken_over
    keep.notes = (keep.notes + f"\n[合并自 #{other.id} {other.name} {other.domain}]").strip()
    db.flush()
    db.delete(other)
    audit(db, actor, "supplier_merged", f"supplier:{keep.id}", f"merged {other.id}")
