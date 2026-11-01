from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Message, ProcurementTask, Supplier, utcnow
from ..skills import engine as skills
from . import messaging, outreach
from . import rules as R


def run(db: Session) -> dict:
    rules = skills.get_rules(db, "followup")
    out = {"checked": 0, "queued": 0, "drafts": 0, "stopped": 0}
    q = db.query(Supplier).filter(Supplier.status.in_(["contacted", "replied"]), Supplier.taken_over.is_(False),
                                  Supplier.opted_out.is_(False), Supplier.last_outbound_at.isnot(None))
    now = utcnow()
    for sup in q.all():
        out["checked"] += 1
        if db.query(Message).filter(Message.supplier_id == sup.id, Message.direction == "out",
                                    Message.status.in_(["draft", "queued"]), Message.created_by == "ai").first():
            continue
        state = {"status": sup.status, "followups": sup.followup_count,
                 "days_since_out": (now - sup.last_outbound_at).total_seconds() / 86400,
                 "replied_after": bool(sup.last_inbound_at and sup.last_inbound_at > sup.last_outbound_at)}
        d = R.followup_decision(state, rules)
        if d["action"] == "stop" and sup.status == "contacted" and sup.followup_count >= rules.get("max_followups", 3):
            sup.status = "closed"
            sup.notes = (sup.notes + "\n[AI] 跟进次数已满且无回复，自动关闭").strip()
            out["stopped"] += 1
        if d["action"] != "followup":
            continue
        msg = outreach.compose_followup(db, sup)
        if msg is None:
            continue
        task = db.get(ProcurementTask, msg.task_id) if msg.task_id else None
        if task and task.auto_outreach:
            ok, _ = messaging.queue(db, msg)
            out["queued"] += int(ok)
        else:
            out["drafts"] += 1
    return out
