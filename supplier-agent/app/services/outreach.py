"""Compose initial, clarification and follow-up messages."""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from ..models import Fact, Message, ProcurementTask, Supplier, SupplierQuestion
from ..skills import engine as skills
from . import llm
from . import rules as R
from . import settings
from .extractor import prefer_emails


def _qtext(criteria: list[dict], keys: list[str]) -> str:
    by = {c["key"]: c for c in criteria}
    return "\n".join(f"{i}. {by[k]['question_en']}" for i, k in enumerate(keys, 1) if k in by)


def render_initial(rules: dict, criteria: list[dict], supplier_name: str, website: str, country: str,
                   service_hint: str, question_keys: list[str], st: dict) -> tuple[str, str]:
    t = rules.get("template", {})
    ctx = {"supplier_name": supplier_name, "website": website, "country": country,
           "service_hint": f" and noticed that you offer {service_hint}" if service_hint else "",
           "company_name": st.get("company_name", ""), "signature": st.get("company_signature", ""),
           "questions": _qtext(criteria, question_keys)}
    return t["subject"].format(**ctx), t["body"].format(**ctx)


def _service_hint(db: Session, sup: Supplier) -> str:
    f = db.query(Fact).filter(Fact.supplier_id == sup.id, Fact.key == "inventory", Fact.polarity == "yes").first()
    if not f:
        return ""
    low = f.snippet.lower()
    for phrase in ("aged companies", "shelf companies", "ready made companies", "ready-made companies",
                   "vintage companies", "off the shelf companies", "vorratsgesellschaften", "società pronte",
                   "sociedades preconstituidas"):
        if phrase in low:
            return phrase
    return "ready-made companies"


_THE = {"United Kingdom", "United States", "Czech Republic", "Netherlands", "United Arab Emirates", "Philippines"}


def task_country(task: ProcurementTask | None, sup: Supplier) -> str:
    name = ""
    if task and task.spec.get("countries"):
        targets = [c["name"] for c in task.spec["countries"]]
        hinted = [c for c in sup.country_hint.split(",") if c in targets]
        name = hinted[0] if hinted else targets[0]
    elif sup.country_hint:
        name = sup.country_hint.split(",")[0]
    if not name:
        return "your jurisdiction"
    return f"the {name}" if name in _THE else name


def compose_initial(db: Session, sup: Supplier, task: ProcurementTask) -> Message | None:
    emails = prefer_emails([{"ctype": c.ctype, "normalized": c.normalized} for c in sup.contacts if not c.bounced],
                           sup.domain or "")
    if not emails:
        return None
    rules = skills.get_rules(db, "outreach")
    inquiry = skills.get_rules(db, "inquiry")
    criteria = skills.criteria(db)
    levels = task.spec.get("levels", {})
    qstate = {q.key: {"asked_count": q.asked_count, "answered": q.answered}
              for q in db.query(SupplierQuestion).filter_by(supplier_id=sup.id)}
    keys = R.next_questions(levels, qstate, inquiry, order=rules.get("first_mail_question_order"),
                            limit=rules.get("max_questions_first_mail", 4))
    st = settings.all_settings(db)
    country = task_country(task, sup)
    subject, body = render_initial(rules, criteria, sup.name or sup.domain, sup.website, country,
                                   _service_hint(db, sup), keys, st)
    origin = "template"
    if llm.available(db):
        data = llm.chat_json(
            db, "compose_initial",
            "You write short, polite B2B procurement enquiry emails. Never promise to buy, pay or sign. "
            "Never invent facts about the supplier. Output JSON {\"subject\":..., \"body\":...}.",
            f"Supplier: {sup.name} ({sup.website}). What their website says: {sup.description[:800]}\n"
            f"We are: {st['company_name']}, cross-border e-commerce, buying ready-made companies in {country}.\n"
            f"Ask exactly these questions (numbered):\n{_qtext(criteria, keys)}\n"
            f"Sign off with:\n{st['company_signature']}\nWrite in English, under 180 words.",
            task_id=task.id)
        if data and data.get("subject") and data.get("body") and not R.check_forbidden(
                data["body"], rules.get("forbidden_phrases", [])):
            subject, body, origin = data["subject"][:300], data["body"], "llm"
    msg = Message(supplier_id=sup.id, task_id=task.id, channel="email", direction="out", kind="initial",
                  subject=subject, body=body, to_addr=emails[0], status="draft", created_by="ai",
                  dedupe_key=f"initial:{sup.id}", analysis={"asked": keys, "composer": origin})
    db.add(msg)
    db.flush()
    return msg


def _thread_root(db: Session, sup: Supplier) -> Message | None:
    return db.query(Message).filter(Message.supplier_id == sup.id, Message.direction == "out",
                                    Message.status == "sent").order_by(Message.sent_at.asc()).first()


def compose_clarify(db: Session, sup: Supplier, inbound: Message, keys: list[str], ack: str) -> Message:
    rules = skills.get_rules(db, "inquiry")
    criteria = skills.criteria(db)
    st = settings.all_settings(db)
    t = rules["template"]
    root = _thread_root(db, sup)
    base_subject = (inbound.subject or (root.subject if root else "")).removeprefix("Re: ").removeprefix("RE: ")
    subject = t["subject"].format(subject=base_subject)
    body = t["body"].format(contact_name=(sup.name or "team"), ack=ack, questions=_qtext(criteria, keys),
                            signature=st["company_signature"])
    digest = hashlib.sha1(("|".join(sorted(keys)) + str(inbound.id)).encode()).hexdigest()[:10]
    msg = Message(supplier_id=sup.id, task_id=inbound.task_id, channel="email", direction="out", kind="clarify",
                  subject=subject, body=body, to_addr=inbound.from_addr, in_reply_to=inbound.header_message_id,
                  status="draft", created_by="ai", dedupe_key=f"clarify:{sup.id}:{digest}",
                  analysis={"asked": keys, "reply_to": inbound.id})
    db.add(msg)
    db.flush()
    return msg


def compose_followup(db: Session, sup: Supplier) -> Message | None:
    rules = skills.get_rules(db, "followup")
    root = _thread_root(db, sup)
    if root is None:
        return None
    last_out = db.query(Message).filter(Message.supplier_id == sup.id, Message.direction == "out",
                                        Message.status == "sent").order_by(Message.sent_at.desc()).first()
    task = db.get(ProcurementTask, root.task_id) if root.task_id else None
    st = settings.all_settings(db)
    t = rules["template"]
    subject = t["subject"].format(subject=root.subject.removeprefix("Re: "))
    body = t["body"].format(contact_name=sup.name or "team", country=task_country(task, sup),
                            signature=st["company_signature"])
    msg = Message(supplier_id=sup.id, task_id=root.task_id, channel="email", direction="out", kind="followup",
                  subject=subject, body=body, to_addr=root.to_addr, in_reply_to=last_out.header_message_id,
                  status="draft", created_by="ai", dedupe_key=f"followup:{sup.id}:{sup.followup_count + 1}",
                  analysis={"asked": [], "followup_no": sup.followup_count + 1})
    db.add(msg)
    db.flush()
    return msg
