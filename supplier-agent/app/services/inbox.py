"""Inbound processing: match reply to supplier, extract answers, decide next step."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..connectors.base import AuthExpired, InboundMessage
from ..connectors.registry import build
from ..models import ChannelAccount, Contact, Message, ProcurementTask, Supplier, SupplierQuestion, utcnow
from ..skills import engine as skills
from . import llm, messaging, outreach
from . import rules as R
from . import settings
from . import suppliers as S
from .logs import audit, notify, syslog


def match_supplier(db: Session, im: InboundMessage) -> tuple[Supplier | None, Message | None]:
    ids = [i for i in [im.in_reply_to, *im.references] if i]
    for mid in reversed(ids):
        orig = db.query(Message).filter_by(header_message_id=mid.strip(), direction="out").first()
        if orig and orig.supplier_id:
            return db.get(Supplier, orig.supplier_id), orig
    c = db.query(Contact).filter_by(ctype="email", normalized=im.from_addr.lower()).first()
    if c:
        return c.supplier, None
    dom = im.from_addr.split("@")[-1].lower()
    sup = db.query(Supplier).filter(Supplier.domain == dom).first()
    return sup, None


def _handle_bounce(db: Session, im: InboundMessage) -> None:
    sup, orig = match_supplier(db, im)
    addrs = set(re.findall(r"[\w.+\-]+@[\w.\-]+\.\w+", im.body))
    if orig:
        addrs.add(orig.to_addr)
        orig.status, orig.error = "failed", "退信: " + im.subject[:200]
    for a in addrs:
        c = db.query(Contact).filter_by(ctype="email", normalized=a.lower()).first()
        if c and not c.bounced:
            c.bounced = True
            audit(db, "system", "contact_bounced", f"contact:{c.id}", a)


def process_inbound(db: Session, im: InboundMessage, channel: str = "email") -> Message:
    if im.header_message_id and db.query(Message).filter_by(header_message_id=im.header_message_id,
                                                            direction="in").first():
        return None
    if im.is_bounce:
        _handle_bounce(db, im)
    sup, orig = match_supplier(db, im)
    msg = Message(supplier_id=sup.id if sup else None, task_id=orig.task_id if orig else None, channel=channel,
                  direction="in", kind="inbound", subject=im.subject, body=im.body, from_addr=im.from_addr,
                  to_addr=im.to_addr, header_message_id=im.header_message_id, in_reply_to=im.in_reply_to,
                  status="received", created_by="supplier")
    db.add(msg)
    db.flush()
    if im.is_bounce or sup is None:
        if sup is None and not im.is_bounce:
            notify(db, "收到无法匹配供应商的邮件", f"{im.from_addr}: {im.subject}", "/messages?filter=unmatched", "warning")
        return msg
    if msg.task_id is None:
        last = db.query(Message).filter(Message.supplier_id == sup.id, Message.task_id.isnot(None)).order_by(
            Message.id.desc()).first()
        msg.task_id = last.task_id if last else None
    sup.last_inbound_at = utcnow()
    analyze_and_act(db, sup, msg, attachments=im.attachments)
    return msg


def analyze_and_act(db: Session, sup: Supplier, msg: Message, attachments: list[str] | None = None) -> dict:
    criteria = skills.criteria(db)
    followup_rules = skills.get_rules(db, "followup")
    handoff_rules = skills.get_rules(db, "handoff")
    inquiry_rules = skills.get_rules(db, "inquiry")
    task = db.get(ProcurementTask, msg.task_id) if msg.task_id else None
    levels = (task.spec.get("levels") if task else {}) or {}
    required = [k for k, v in levels.items() if v == "required"]
    text = R.strip_quoted(msg.body)
    if attachments:
        text += "\n[attached: " + ", ".join(attachments) + "]"
    analysis: dict = {"clean_text": text[:4000]}

    if R.is_opt_out(text, followup_rules.get("opt_out_patterns", [])):
        sup.opted_out, sup.status, sup.intent_level = True, "opted_out", "none"
        n = messaging.cancel_pending_for_supplier(db, sup.id, "供应商拒绝/退订，停止联系")
        analysis.update({"action": "stop", "reason": "供应商拒绝或要求停止联系", "cancelled": n})
        msg.analysis = analysis
        audit(db, "ai", "supplier_opted_out", f"supplier:{sup.id}", text[:300])
        return analysis

    detected = R.detect_criteria(text, criteria)
    status = "doc_provided" if attachments else "supplier_claim"
    for key, d in detected.items():
        if key == "price":
            for pr in d.get("prices", [])[:5]:
                S.add_fact(db, sup, "price", "yes", "supplier_claim", pr["snippet"], message_id=msg.id,
                           amount=pr["amount"], currency=pr["currency"], value=f"{pr['currency']} {pr['amount']:,.0f}")
        else:
            S.add_fact(db, sup, key, d["polarity"], status, d["snippet"], message_id=msg.id)
        q = db.query(SupplierQuestion).filter_by(supplier_id=sup.id, key=key).first()
        if q is None:
            q = SupplierQuestion(supplier_id=sup.id, key=key)
            db.add(q)
        if not q.answered:
            q.answered, q.answer_text, q.answer_message_id = True, d["snippet"][:1000], msg.id
    db.flush()

    risk = R.detect_risk(text, skills.get_rules(db, "risk").get("patterns", []))
    if risk["level"] == "high" or (risk["level"] == "medium" and sup.risk_level in ("low", "unknown")):
        sup.risk_level = risk["level"]

    extra = []
    llm_view = None
    if llm.available(db):
        llm_view = llm.chat_json(
            db, "analyze_reply",
            "You analyse supplier replies for a procurement team. Output JSON only. Do not invent facts.",
            "Reply:\n" + text[:6000] + "\n\nReturn {\"signals\": subset of [has_inventory, provided_price, willing, "
            "documents, next_steps], \"summary_zh\": \"中文摘要\", \"translation_zh\": \"中文全文翻译\"}",
            task_id=msg.task_id)
        if llm_view:
            extra = [s for s in llm_view.get("signals", []) if s in ("has_inventory", "willing", "documents")]
            msg.body_zh = llm_view.get("translation_zh") or ""
            analysis["summary_zh"] = llm_view.get("summary_zh", "")

    intent = R.compute_intent(text, handoff_rules, criteria, required,
                              followup_rules.get("opt_out_patterns", []), extra_signals=extra)
    intent.pop("detected", None)
    analysis.update({"intent": intent, "detected": {k: v["polarity"] for k, v in detected.items()},
                     "risk": risk, "llm": bool(llm_view)})
    sup.intent_score = max(sup.intent_score or 0, intent["score"])
    if intent["level"] != "none":
        order = ["none", "low", "medium", "high"]
        if order.index(intent["level"]) > order.index(sup.intent_level or "none"):
            sup.intent_level = intent["level"]
    if sup.status in ("new", "screened", "contacted"):
        sup.status = "replied"
    if task:
        S.screen_supplier(db, sup, task)

    if sup.taken_over:
        analysis["action"] = "human"
        analysis["reason"] = "已人工接管：仅整理资料，不自动回复"
        msg.analysis = analysis
        return analysis

    if intent["handoff"]:
        labels = {s["key"]: s["label"] for s in handoff_rules.get("signals", [])}
        reason = f"{intent['reason']}；信号：" + "、".join(labels.get(s, s) for s in intent["signals"])
        S.create_handoff(db, sup, reason, intent["score"], intent["signals"])
        analysis.update({"action": "handoff", "reason": reason})
        msg.analysis = analysis
        return analysis

    qstate = {q.key: {"asked_count": q.asked_count, "answered": q.answered}
              for q in db.query(SupplierQuestion).filter_by(supplier_id=sup.id)}
    keys = R.next_questions(levels, qstate, inquiry_rules)
    if not keys:
        analysis.update({"action": "none", "reason": "没有需要追问的问题"})
        msg.analysis = analysis
        return analysis
    ack = " and the information provided" if detected else ""
    reply = outreach.compose_clarify(db, sup, msg, keys, ack)
    if task and task.auto_outreach:
        ok, why = messaging.queue(db, reply)
        analysis.update({"action": "clarify_queued" if ok else "clarify_blocked", "reason": why, "questions": keys,
                         "reply_id": reply.id})
    else:
        analysis.update({"action": "clarify_draft", "questions": keys, "reply_id": reply.id})
    msg.analysis = analysis
    return analysis


def poll_all(db: Session) -> dict:
    out = {"accounts": 0, "messages": 0, "errors": []}
    for acc in db.query(ChannelAccount).filter(ChannelAccount.platform == "email",
                                               ChannelAccount.status.in_(["active", "unverified"])).all():
        conn = build(acc)
        if not conn.cfg.get("imap_host"):
            continue
        state = settings.get(db, f"imap_state_{acc.id}") or {}
        try:
            msgs, state = conn.fetch_new(dict(state))
        except AuthExpired as e:
            acc.status, acc.last_error = "expired", str(e)
            notify(db, f"邮箱授权失效：{acc.name}", str(e), "/accounts", "error")
            out["errors"].append(str(e))
            continue
        except Exception as e:
            acc.last_error = f"{type(e).__name__}: {e}"
            syslog("ERROR", "inbox", f"{acc.name}: {acc.last_error}")
            out["errors"].append(acc.last_error)
            continue
        own = (conn.cfg.get("from_addr") or "").lower()
        for im in msgs:
            if im.from_addr == own:
                continue
            try:
                with db.begin_nested():
                    process_inbound(db, im)
                out["messages"] += 1
            except Exception as e:
                syslog("ERROR", "inbox", f"处理邮件失败 {im.header_message_id}: {type(e).__name__}: {e}")
        settings.set_(db, f"imap_state_{acc.id}", state)
        out["accounts"] += 1
    return out
