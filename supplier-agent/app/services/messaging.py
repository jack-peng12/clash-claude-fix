"""Outbound message lifecycle: guard checks, queueing, delivery with retry, sandbox redirect."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from ..connectors.base import AuthExpired
from ..connectors.registry import build, default_account
from ..models import Contact, Job, Message, Supplier, SupplierQuestion, utcnow
from ..skills import engine as skills
from . import rules as R
from . import settings
from .logs import audit, notify, syslog

RETRY_DELAYS_MIN = [2, 10, 60]


def new_message_id(domain: str = "supplier-agent.local") -> str:
    return f"<{uuid.uuid4().hex}@{domain}>"


def check_outbound(db: Session, msg: Message, at_send_time: bool = False) -> tuple[bool, str]:
    """Returns (allowed, reason). Called when queueing AND again right before delivery."""
    if not settings.get(db, "outbound_enabled"):
        return False, "系统对外发送总开关已关闭"
    sup = db.get(Supplier, msg.supplier_id) if msg.supplier_id else None
    if sup is None:
        return False, "消息未关联供应商"
    if msg.created_by == "ai":
        if sup.taken_over:
            return False, "供应商已转人工接管，AI 不得对外发送"
        if sup.opted_out or sup.status in ("opted_out", "rejected", "closed"):
            return False, f"供应商状态为 {sup.status}，停止联系"
    elif sup.opted_out:
        return False, "供应商已要求停止联系"
    if not msg.to_addr:
        return False, "无收件地址"
    c = db.query(Contact).filter_by(ctype="email", normalized=msg.to_addr.lower()).first()
    if c is not None and c.bounced:
        return False, "该邮箱曾退信，已标记无效"
    forbidden = R.check_forbidden(msg.subject + "\n" + msg.body, skills.get_rules(db, "outreach").get("forbidden_phrases", []))
    if forbidden:
        return False, f"含越权表述（签约/付款/承诺）: {forbidden}"
    sent_q = db.query(Message).filter(Message.supplier_id == sup.id, Message.direction == "out",
                                      Message.id != msg.id)
    if msg.kind == "initial" and sent_q.filter(Message.kind == "initial",
                                               Message.status.in_(["queued", "sent"])).first():
        return False, "重复发送拦截：该供应商已发送过首封开发信"
    if msg.dedupe_key and sent_q.filter(Message.dedupe_key == msg.dedupe_key,
                                        Message.status.in_(["queued", "sent"])).first():
        return False, "重复发送拦截：相同内容已发送"
    if msg.created_by == "ai" and msg.kind in ("initial", "followup"):
        min_h = float(settings.get(db, "min_hours_between_messages"))
        last = sent_q.filter(Message.status == "sent").order_by(Message.sent_at.desc()).first()
        if last and last.sent_at and utcnow() - last.sent_at < timedelta(hours=min_h):
            return False, f"距上次发送不足 {min_h:g} 小时"
    if at_send_time:
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        sent_today = db.query(Message).filter(Message.direction == "out", Message.status == "sent",
                                              Message.sent_at >= day_start).count()
        if sent_today >= int(settings.get(db, "daily_send_limit")):
            return False, "已达今日发送上限"
    return True, ""


def queue(db: Session, msg: Message, actor: str = "ai") -> tuple[bool, str]:
    ok, reason = check_outbound(db, msg)
    if not ok:
        msg.status, msg.error = "blocked", reason
        audit(db, actor, "message_blocked", f"message:{msg.id}", reason)
        return False, reason
    msg.status = "queued"
    db.flush()
    db.add(Job(jtype="send_message", payload={"message_id": msg.id}))
    audit(db, actor, "message_queued", f"message:{msg.id}", msg.subject)
    return True, ""


def deliver(db: Session, message_id: int) -> str:
    msg = db.get(Message, message_id)
    if msg is None or msg.status != "queued":
        return "skip"
    ok, reason = check_outbound(db, msg, at_send_time=True)
    if not ok:
        if reason == "已达今日发送上限":
            db.add(Job(jtype="send_message", payload={"message_id": msg.id},
                       run_after=utcnow() + timedelta(hours=1)))
            return "deferred"
        msg.status, msg.error = "blocked", reason
        audit(db, "system", "message_blocked", f"message:{msg.id}", reason)
        return "blocked"
    acc = default_account(db, msg.channel)
    if acc is None:
        msg.status, msg.error = "failed", f"没有可用的 {msg.channel} 账号"
        notify(db, "发送失败：未配置邮箱账号", "请在“账号管理”添加邮箱。", "/accounts", "error")
        return "failed"
    if acc.status == "expired":
        msg.status, msg.error = "failed", "账号授权已失效，请重新授权后重试"
        return "failed"
    sandbox = bool(settings.get(db, "sandbox_mode"))
    actual_to = settings.get(db, "sandbox_address") if sandbox else msg.to_addr
    subject = f"[SANDBOX→{msg.to_addr}] {msg.subject}" if sandbox else msg.subject
    if not msg.header_message_id:
        msg.header_message_id = new_message_id()
    msg.attempts += 1
    try:
        conn = build(acc)
        conn.send(actual_to, subject, msg.body, msg.header_message_id, msg.in_reply_to)
    except AuthExpired as e:
        acc.status, acc.last_error = "expired", str(e)
        msg.status, msg.error = "failed", f"账号授权失效: {e}"
        notify(db, f"邮箱授权失效：{acc.name}", str(e), "/accounts", "error")
        return "failed"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:1000]
        msg.error = err
        if msg.attempts <= len(RETRY_DELAYS_MIN):
            db.add(Job(jtype="send_message", payload={"message_id": msg.id},
                       run_after=utcnow() + timedelta(minutes=RETRY_DELAYS_MIN[msg.attempts - 1])))
            syslog("WARNING", "mail", f"发送失败将重试 message={msg.id}: {err}")
            return "retry"
        msg.status = "failed"
        notify(db, "邮件发送失败", f"消息 {msg.id} 重试 {msg.attempts} 次仍失败: {err}", f"/suppliers/{msg.supplier_id}", "error")
        return "failed"
    msg.status, msg.sent_at, msg.actual_to_addr, msg.error = "sent", utcnow(), actual_to, ""
    msg.from_addr = build(acc).cfg.get("from_addr", "")
    sup = db.get(Supplier, msg.supplier_id)
    sup.last_outbound_at = msg.sent_at
    if sup.status in ("new", "screened"):
        sup.status = "contacted"
    if msg.kind == "followup":
        sup.followup_count += 1
    for key in (msg.analysis or {}).get("asked", []):
        q = db.query(SupplierQuestion).filter_by(supplier_id=sup.id, key=key).first()
        if q is None:
            q = SupplierQuestion(supplier_id=sup.id, key=key, asked_count=0)
            db.add(q)
        q.asked_count += 1
        q.last_asked_at = msg.sent_at
    audit(db, msg.created_by, "message_sent", f"message:{msg.id}",
          f"to={msg.to_addr} actual={actual_to} sandbox={sandbox}")
    return "sent"


def cancel_pending_for_supplier(db: Session, supplier_id: int, reason: str) -> int:
    n = 0
    for m in db.query(Message).filter(Message.supplier_id == supplier_id, Message.direction == "out",
                                      Message.created_by == "ai",
                                      Message.status.in_(["draft", "approved", "queued"])).all():
        m.status, m.error = "blocked", reason
        n += 1
    return n
