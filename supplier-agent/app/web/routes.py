from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..connectors.registry import CONNECTORS, verify_account
from ..db import get_db
from ..models import (
    AuditLog,
    ChannelAccount,
    Contact,
    CostRecord,
    Evidence,
    Fact,
    Handoff,
    Job,
    ManualAction,
    Message,
    Notification,
    ProcurementTask,
    SearchRun,
    Skill,
    SkillVersion,
    Supplier,
    SupplierQuestion,
    SupplierTask,
    SystemLog,
    User,
    utcnow,
)
from ..security import encrypt_json, decrypt_json, hash_password, verify_password
from ..services import llm, messaging, settings
from ..services import suppliers as S
from ..services.logs import audit
from ..services.requirement_parser import parse
from ..skills import engine as skills
from .deps import ROLE_RANK, current_user, render, require

router = APIRouter()


def get_or_404(db: Session, model, pk: int):
    obj = db.get(model, pk)
    if obj is None:
        raise HTTPException(404)
    return obj


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ------------------------------------------------------------------ auth
@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    return render(request, db, None, "login.html", error="")


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    u = db.query(User).filter_by(username=username.strip()).first()
    if not u or not u.active or not verify_password(password, u.password_hash):
        return render(request, db, None, "login.html", error="用户名或密码错误")
    request.session["uid"] = u.id
    audit(db, u.username, "login")
    db.commit()
    return back("/")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return back("/login")


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {"ok": True, "suppliers": db.query(Supplier).count()}


# ------------------------------------------------------------------ dashboard
@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cat_counts = dict(db.query(Supplier.fit_category, func.count()).group_by(Supplier.fit_category).all())
    status_counts = dict(db.query(Supplier.status, func.count()).group_by(Supplier.status).all())
    day = utcnow() - timedelta(days=1)
    stats = {
        "suppliers": db.query(Supplier).count(),
        "tasks_running": db.query(ProcurementTask).filter(ProcurementTask.status.in_(["running", "queued"])).count(),
        "sent_24h": db.query(Message).filter(Message.direction == "out", Message.status == "sent",
                                             Message.sent_at >= day).count(),
        "in_24h": db.query(Message).filter(Message.direction == "in", Message.created_at >= day).count(),
        "handoff_open": db.query(Handoff).filter_by(status="open").count(),
        "drafts": db.query(Message).filter_by(direction="out", status="draft").count(),
        "manual": db.query(ManualAction).filter_by(status="pending").count(),
    }
    notes = db.query(Notification).order_by(Notification.id.desc()).limit(15).all()
    jobs = db.query(Job).order_by(Job.id.desc()).limit(10).all()
    return render(request, db, user, "dashboard.html", stats=stats, cat_counts=cat_counts,
                  status_counts=status_counts, notes=notes, jobs=jobs, budget=llm.budget_status(db),
                  st=settings.all_settings(db), llm_on=llm.available(db))


@router.post("/notifications/read")
def notifications_read(db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.query(Notification).update({"read": True})
    db.commit()
    return back("/")


@router.post("/jobs/run/{jtype}")
def run_job_now(jtype: str, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    if jtype not in ("poll_inbox", "followups", "backup"):
        raise HTTPException(400)
    db.add(Job(jtype=jtype, payload={}, max_attempts=1))
    audit(db, user.username, f"job_{jtype}_manual")
    db.commit()
    return back("/")


# ------------------------------------------------------------------ tasks
@router.get("/tasks")
def tasks(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(ProcurementTask).order_by(ProcurementTask.id.desc()).all()
    counts = dict(db.query(SupplierTask.task_id, func.count()).group_by(SupplierTask.task_id).all())
    return render(request, db, user, "tasks.html", tasks=rows, counts=counts)


@router.get("/tasks/new")
def task_new(request: Request, template_id: int | None = None, db: Session = Depends(get_db),
             user: User = Depends(require("staff"))):
    tpl = db.get(ProcurementTask, template_id) if template_id else None
    templates_ = db.query(ProcurementTask).filter_by(is_template=True).all()
    return render(request, db, user, "task_new.html", tpl=tpl, templates_=templates_, preview=None, raw="")


@router.post("/tasks/parse")
def task_parse(request: Request, raw_text: str = Form(...), db: Session = Depends(get_db),
               user: User = Depends(require("staff"))):
    spec = parse(db, raw_text, skills.criteria(db))
    db.commit()
    return render(request, db, user, "task_new.html", tpl=None, templates_=[], preview=spec, raw=raw_text,
                  criteria=skills.criteria(db))


def _spec_from_form(form, base: dict, criteria: list[dict]) -> dict:
    spec = dict(base)
    levels = {}
    for c in criteria:
        v = form.get(f"level_{c['key']}")
        if v and v in ("required", "preferred", "to_confirm", "not_required"):
            levels[c["key"]] = v
    spec["levels"] = levels
    if form.get("target_suppliers"):
        spec["target_suppliers"] = int(form.get("target_suppliers"))
    if form.get("countries") is not None:
        from ..services.countries import find_by_name

        cs = [find_by_name(x) for x in form.get("countries").replace("，", ",").split(",") if x.strip()]
        spec["countries"] = [c for c in cs if c]
    if form.get("company_types") is not None:
        spec["company_types"] = [x.strip() for x in form.get("company_types").replace("，", ",").split(",") if x.strip()]
    return spec


@router.post("/tasks")
async def task_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    form = await request.form()
    base = json.loads(form.get("spec_json") or "{}")
    spec = _spec_from_form(form, base, skills.criteria(db))
    if not spec.get("countries"):
        raise HTTPException(400, "请至少指定一个可识别的国家（中文或英文名）")
    t = ProcurementTask(title=form.get("title") or "采购任务", raw_text=form.get("raw_text") or "", spec=spec,
                        auto_outreach=form.get("auto_outreach") == "on", continuous=form.get("continuous") == "on",
                        is_template=form.get("is_template") == "on", created_by=user.id)
    db.add(t)
    db.flush()
    audit(db, user.username, "task_created", f"task:{t.id}", json.dumps(spec, ensure_ascii=False)[:2000])
    if form.get("start_now") == "on" and not t.is_template:
        t.status = "queued"
        db.add(Job(jtype="task_round", payload={"task_id": t.id}))
    db.commit()
    return back(f"/tasks/{t.id}")


@router.get("/tasks/{tid}")
def task_detail(tid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, ProcurementTask, tid)
    links = (db.query(SupplierTask, Supplier).join(Supplier, Supplier.id == SupplierTask.supplier_id)
             .filter(SupplierTask.task_id == tid).order_by(SupplierTask.fit_score.desc()).all())
    runs = db.query(SearchRun).filter_by(task_id=tid).order_by(SearchRun.id.desc()).all()
    jobs = db.query(Job).filter(Job.jtype == "task_round").order_by(Job.id.desc()).limit(50).all()
    jobs = [j for j in jobs if (j.payload or {}).get("task_id") == tid][:5]
    return render(request, db, user, "task_detail.html", t=t, links=links, runs=runs, jobs=jobs,
                  criteria=skills.criteria(db))


@router.post("/tasks/{tid}/edit")
async def task_edit(tid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    t = db.get(ProcurementTask, tid)
    form = await request.form()
    t.spec = _spec_from_form(form, t.spec, skills.criteria(db))
    t.title = form.get("title") or t.title
    t.auto_outreach = form.get("auto_outreach") == "on"
    t.continuous = form.get("continuous") == "on"
    t.is_template = form.get("is_template") == "on"
    audit(db, user.username, "task_edited", f"task:{tid}")
    db.commit()
    return back(f"/tasks/{tid}")


@router.post("/tasks/{tid}/action/{action}")
def task_action(tid: int, action: str, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    t = db.get(ProcurementTask, tid)
    if action in ("start", "resume"):
        if t.status in ("running", "queued"):
            return back(f"/tasks/{tid}")
        t.status = "queued"
        db.add(Job(jtype="task_round", payload={"task_id": tid}))
    elif action == "pause":
        t.status = "paused"
    elif action == "cancel":
        t.status = "cancelled"
        for m in db.query(Message).filter(Message.task_id == tid, Message.created_by == "ai",
                                          Message.status.in_(["draft", "queued"])).all():
            m.status, m.error = "blocked", "任务已取消"
    elif action == "clone":
        n = ProcurementTask(title=t.title + "（复制）", raw_text=t.raw_text, spec=t.spec, auto_outreach=t.auto_outreach,
                            continuous=t.continuous, created_by=user.id)
        db.add(n)
        db.flush()
        audit(db, user.username, "task_cloned", f"task:{n.id}")
        db.commit()
        return back(f"/tasks/{n.id}")
    else:
        raise HTTPException(400)
    audit(db, user.username, f"task_{action}", f"task:{tid}")
    db.commit()
    return back(f"/tasks/{tid}")


# ------------------------------------------------------------------ suppliers
@router.get("/suppliers")
def suppliers(request: Request, q: str = "", cat: str = "", status: str = "", intent: str = "",
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    qry = db.query(Supplier)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Supplier.name.ilike(like)) | (Supplier.domain.ilike(like)) | (Supplier.country_hint.ilike(like)))
    if cat:
        qry = qry.filter(Supplier.fit_category == cat)
    if status:
        qry = qry.filter(Supplier.status == status)
    if intent:
        qry = qry.filter(Supplier.intent_level == intent)
    rows = qry.order_by(Supplier.intent_score.desc(), Supplier.fit_score.desc(), Supplier.id.desc()).limit(500).all()
    return render(request, db, user, "suppliers.html", rows=rows, q=q, cat=cat, status=status, intent=intent)


@router.get("/suppliers/{sid}")
def supplier_detail(sid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_or_404(db, Supplier, sid)
    msgs = db.query(Message).filter_by(supplier_id=sid).order_by(Message.created_at.asc()).all()
    facts = db.query(Fact).filter_by(supplier_id=sid).order_by(Fact.key, Fact.created_at).all()
    evidence = db.query(Evidence).filter_by(supplier_id=sid).order_by(Evidence.id.desc()).all()
    questions = db.query(SupplierQuestion).filter_by(supplier_id=sid).all()
    handoffs = db.query(Handoff).filter_by(supplier_id=sid).order_by(Handoff.id.desc()).all()
    links = db.query(SupplierTask, ProcurementTask).join(ProcurementTask, ProcurementTask.id == SupplierTask.task_id) \
        .filter(SupplierTask.supplier_id == sid).all()
    labels = {c["key"]: c["label"] for c in skills.criteria(db)}
    return render(request, db, user, "supplier_detail.html", s=s, msgs=msgs, facts=facts, evidence=evidence,
                  questions=questions, handoffs=handoffs, links=links, clabels=labels,
                  summary=S.fact_summary(db, s), audit_rows=db.query(AuditLog).filter(
                      AuditLog.target == f"supplier:{sid}").order_by(AuditLog.id.desc()).limit(30).all())


@router.post("/suppliers/{sid}/takeover")
def supplier_takeover(sid: int, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    S.manual_takeover(db, db.get(Supplier, sid), user.id, user.username)
    db.commit()
    return back(f"/suppliers/{sid}")


@router.post("/suppliers/{sid}/release")
def supplier_release(sid: int, db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    S.release_to_ai(db, db.get(Supplier, sid), user.username)
    db.commit()
    return back(f"/suppliers/{sid}")


@router.post("/suppliers/{sid}/update")
def supplier_update(sid: int, name: str = Form(""), notes: str = Form(""), status: str = Form(""),
                    db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    s = db.get(Supplier, sid)
    if name:
        s.name = name
    s.notes = notes
    if status in ("rejected", "closed", "opted_out"):
        s.status = status
        s.opted_out = s.opted_out or status == "opted_out"
        messaging.cancel_pending_for_supplier(db, sid, f"员工将状态改为 {status}")
    audit(db, user.username, "supplier_updated", f"supplier:{sid}", f"status={status}")
    db.commit()
    return back(f"/suppliers/{sid}")


@router.post("/suppliers/{sid}/merge")
def supplier_merge(sid: int, other_id: int = Form(...), db: Session = Depends(get_db),
                   user: User = Depends(require("manager"))):
    S.merge(db, db.get(Supplier, sid), db.get(Supplier, other_id), user.username)
    db.commit()
    return back(f"/suppliers/{sid}")


@router.post("/facts/{fid}/verify")
def fact_verify(fid: int, polarity: str = Form("yes"), note: str = Form(""), db: Session = Depends(get_db),
                user: User = Depends(require("staff"))):
    f = db.get(Fact, fid)
    db.add(Fact(supplier_id=f.supplier_id, key=f.key, polarity=polarity, status="human_verified",
                snippet=f"[{user.username} 人工核验] {note} ← {f.snippet[:300]}", evidence_id=f.evidence_id,
                message_id=f.message_id, amount=f.amount, currency=f.currency, value=f.value))
    audit(db, user.username, "fact_verified", f"supplier:{f.supplier_id}", f"{f.key}={polarity} {note}")
    db.commit()
    return back(f"/suppliers/{f.supplier_id}")


@router.post("/suppliers/{sid}/compose")
def supplier_compose(sid: int, subject: str = Form(...), body: str = Form(...), to_addr: str = Form(...),
                     db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    """A human-written message. Allowed even after takeover because the employee is the sender."""
    s = db.get(Supplier, sid)
    last_in = db.query(Message).filter_by(supplier_id=sid, direction="in").order_by(Message.id.desc()).first()
    m = Message(supplier_id=sid, task_id=last_in.task_id if last_in else None, channel="email", direction="out",
                kind="manual", subject=subject, body=body, to_addr=to_addr.strip(),
                in_reply_to=last_in.header_message_id if last_in else "", created_by=f"user:{user.username}",
                dedupe_key=f"manual:{sid}:{utcnow().timestamp()}")
    db.add(m)
    db.flush()
    ok, why = messaging.queue(db, m, actor=user.username)
    db.commit()
    if not ok:
        raise HTTPException(400, why)
    return back(f"/suppliers/{s.id}")


@router.post("/suppliers/{sid}/draft")
def supplier_ai_draft(sid: int, instruction: str = Form(""), db: Session = Depends(get_db),
                      user: User = Depends(require("staff"))):
    """AI assistance after takeover: prepare a draft for the employee, never sent automatically."""
    s = db.get(Supplier, sid)
    history = db.query(Message).filter_by(supplier_id=sid).order_by(Message.id.desc()).limit(6).all()
    convo = "\n\n".join(f"[{m.direction}] {m.subject}\n{m.body[:1500]}" for m in reversed(history))
    text = llm.chat(db, "assist_draft",
                    "You draft replies for a human procurement officer. Never agree to pay, sign or commit. "
                    "Output only the email body in English.",
                    f"Conversation:\n{convo}\n\nInstruction from the officer (Chinese): {instruction}")
    if not text:
        text = "（LLM 未配置或预算已用尽，无法生成草稿。请手动撰写。）"
    db.add(Message(supplier_id=sid, channel="email", direction="out", kind="suggestion", subject="Re: ",
                   body=text, status="draft", created_by="ai", analysis={"instruction": instruction}))
    db.commit()
    return back(f"/suppliers/{s.id}#messages")


# ------------------------------------------------------------------ evidence
@router.get("/evidence/{eid}")
def evidence_view(eid: int, request: Request, raw: int = 0, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    e = db.get(Evidence, eid)
    if raw and e.html_path:
        return FileResponse(config.DATA_DIR / e.html_path, media_type="text/plain; charset=utf-8")
    text = (config.DATA_DIR / e.text_path).read_text(encoding="utf-8") if e.text_path else e.error
    return render(request, db, user, "evidence.html", e=e, text=text)


# ------------------------------------------------------------------ messages
@router.get("/messages")
def messages(request: Request, filter: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(Message)
    if filter == "drafts":
        q = q.filter(Message.direction == "out", Message.status == "draft")
    elif filter == "unmatched":
        q = q.filter(Message.direction == "in", Message.supplier_id.is_(None))
    elif filter == "inbound":
        q = q.filter(Message.direction == "in")
    elif filter == "failed":
        q = q.filter(Message.status.in_(["failed", "blocked"]))
    elif filter == "sent":
        q = q.filter(Message.status == "sent")
    rows = q.order_by(Message.id.desc()).limit(300).all()
    sups = {s.id: s for s in db.query(Supplier).filter(Supplier.id.in_({m.supplier_id for m in rows if m.supplier_id}))}
    return render(request, db, user, "messages.html", rows=rows, sups=sups, filter=filter)


@router.get("/messages/{mid}")
def message_detail(mid: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = db.get(Message, mid)
    return render(request, db, user, "message_detail.html", m=m, s=db.get(Supplier, m.supplier_id) if m.supplier_id else None)


@router.post("/messages/{mid}/update")
def message_update(mid: int, subject: str = Form(...), body: str = Form(...), to_addr: str = Form(""),
                   action: str = Form("save"), db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    m = db.get(Message, mid)
    if m.status not in ("draft", "failed", "blocked"):
        raise HTTPException(400, "只有草稿/失败/拦截的消息可以修改")
    m.subject, m.body = subject, body
    if to_addr:
        m.to_addr = to_addr.strip()
    if action == "approve":
        if m.kind == "suggestion" or (m.supplier_id and db.get(Supplier, m.supplier_id).taken_over):
            m.created_by = f"user:{user.username}"
            m.kind = "manual" if m.kind == "suggestion" else m.kind
        m.status = "draft"
        m.error = ""
        m.attempts = 0
        ok, why = messaging.queue(db, m, actor=user.username)
        audit(db, user.username, "message_approved", f"message:{mid}", why)
    elif action == "discard":
        m.status, m.error = "blocked", f"员工 {user.username} 放弃发送"
    db.commit()
    return back(f"/messages/{mid}")


@router.post("/messages/{mid}/assign")
def message_assign(mid: int, supplier_id: int = Form(...), db: Session = Depends(get_db),
                   user: User = Depends(require("staff"))):
    from ..services.inbox import analyze_and_act

    m = db.get(Message, mid)
    s = db.get(Supplier, supplier_id)
    m.supplier_id = s.id
    if not db.query(Contact).filter_by(ctype="email", normalized=m.from_addr.lower()).first():
        db.add(Contact(supplier_id=s.id, ctype="email", value=m.from_addr, normalized=m.from_addr.lower(),
                       source_url="人工关联来信"))
    db.flush()
    analyze_and_act(db, s, m)
    audit(db, user.username, "message_assigned", f"supplier:{s.id}", f"message {mid}")
    db.commit()
    return back(f"/suppliers/{s.id}")


# ------------------------------------------------------------------ handoffs & quotes
@router.get("/handoffs")
def handoffs(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(Handoff, Supplier).join(Supplier, Supplier.id == Handoff.supplier_id).order_by(
        Handoff.status.desc(), Handoff.id.desc()).all()
    users = {u.id: u for u in db.query(User).all()}
    return render(request, db, user, "handoffs.html", rows=rows, users=users)


@router.post("/handoffs/{hid}/{action}")
def handoff_action(hid: int, action: str, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    h = db.get(Handoff, hid)
    if action == "accept":
        S.accept_handoff(db, h, user.id, user.username)
    elif action == "close":
        h.status = "closed"
        audit(db, user.username, "handoff_closed", f"supplier:{h.supplier_id}")
    db.commit()
    return back("/handoffs")


@router.get("/quotes")
def quotes(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = (db.query(Fact, Supplier).join(Supplier, Supplier.id == Fact.supplier_id)
            .filter(Fact.key == "price", Fact.amount.isnot(None)).order_by(Fact.currency, Fact.amount).all())
    return render(request, db, user, "quotes.html", rows=rows)


# ------------------------------------------------------------------ manual actions
@router.get("/manual")
def manual(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(ManualAction).order_by(ManualAction.status.desc(), ManualAction.id.desc()).limit(300).all()
    sups = {s.id: s for s in db.query(Supplier).filter(Supplier.id.in_({r.supplier_id for r in rows if r.supplier_id}))}
    return render(request, db, user, "manual.html", rows=rows, sups=sups)


@router.post("/manual/{aid}/{action}")
def manual_action(aid: int, action: str, db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    a = db.get(ManualAction, aid)
    a.status = {"done": "done", "skip": "skipped"}.get(action, a.status)
    audit(db, user.username, f"manual_{action}", f"manual:{aid}")
    db.commit()
    return back("/manual")


@router.post("/manual/post-draft")
def manual_post_draft(platform: str = Form(...), task_id: int = Form(...), db: Session = Depends(get_db),
                      user: User = Depends(require("staff"))):
    """Generate a 'wanted' post for a community platform; a human publishes it."""
    t = db.get(ProcurementTask, task_id)
    labels = {c["key"]: c["label"] for c in skills.criteria(db)}
    req = [labels.get(k, k) for k, v in t.spec.get("levels", {}).items() if v == "required"]
    countries = ", ".join(c["name"] for c in t.spec.get("countries", []))
    text = llm.chat(db, "post_draft", "Write a short, honest 'looking to buy' post for a business community. "
                    "No promises of payment. Output only the post.",
                    f"Platform: {platform}. Looking for ready-made companies in {countries}. Requirements: {req}")
    if not text:
        text = (f"[WTB] Ready-made companies in {countries}\n\nWe are a cross-border e-commerce company looking for "
                f"reputable providers of ready-made (shelf) companies in {countries}. Please share availability, "
                f"incorporation dates, prices and what is included (VAT, bank account, director services).\n"
                f"Serious providers only – please DM or comment.")
    db.add(ManualAction(platform=platform, action="post", task_id=task_id, target="（由员工选择合规的群组/版块）",
                        content=text))
    db.commit()
    return back("/manual")


# ------------------------------------------------------------------ skills
@router.get("/skills")
def skills_list(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(Skill).order_by(Skill.id).all()
    vers = {}
    for s in rows:
        vers[s.id] = db.query(SkillVersion).filter_by(skill_id=s.id).order_by(SkillVersion.version.desc()).all()
    return render(request, db, user, "skills.html", rows=rows, vers=vers)


@router.get("/skills/{key}")
def skill_detail(key: str, request: Request, v: int | None = None, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    s = db.query(Skill).filter_by(key=key).one()
    versions = db.query(SkillVersion).filter_by(skill_id=s.id).order_by(SkillVersion.version.desc()).all()
    cur = next((x for x in versions if x.version == (v or s.active_version)), versions[0])
    result = skills.run_tests(key, cur.content)
    return render(request, db, user, "skill_detail.html", s=s, versions=versions, cur=cur, result=result,
                  content_json=json.dumps(cur.content, ensure_ascii=False, indent=2), error="")


@router.post("/skills/{key}/save")
def skill_save(key: str, request: Request, content: str = Form(...), note: str = Form(""),
               activate: str = Form(""), db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    s = db.query(Skill).filter_by(key=key).one()
    try:
        data = json.loads(content)
        v = skills.save_version(db, key, data, note, user.username, activate == "on")
    except (ValueError, KeyError) as e:
        db.rollback()
        versions = db.query(SkillVersion).filter_by(skill_id=s.id).order_by(SkillVersion.version.desc()).all()
        cur = versions[0]
        return render(request, db, user, "skill_detail.html", s=s, versions=versions, cur=cur,
                      result=skills.run_tests(key, cur.content), content_json=content, error=str(e))
    audit(db, user.username, "skill_saved", f"skill:{key}", f"v{v.version} activate={activate} {note}")
    db.commit()
    return back(f"/skills/{key}?v={v.version}")


@router.post("/skills/{key}/activate/{version}")
def skill_activate(key: str, version: int, db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    s = db.query(Skill).filter_by(key=key).one()
    v = db.query(SkillVersion).filter_by(skill_id=s.id, version=version).one()
    if not skills.run_tests(key, v.content)["passed"]:
        raise HTTPException(400, "该版本测试未通过，不能启用")
    s.active_version = version
    audit(db, user.username, "skill_activated", f"skill:{key}", f"v{version}")
    db.commit()
    return back(f"/skills/{key}")


# ------------------------------------------------------------------ accounts
@router.get("/accounts")
def accounts(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.query(ChannelAccount).order_by(ChannelAccount.platform, ChannelAccount.id).all()
    return render(request, db, user, "accounts.html", rows=rows, connectors=CONNECTORS)


@router.post("/accounts")
async def account_create(request: Request, db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    form = await request.form()
    platform = form.get("platform")
    cls = CONNECTORS[platform]
    cfg = {name: (form.get(f"cfg_{name}") or "").strip() for name, _, _ in cls.config_fields}
    acc_id = form.get("account_id")
    if acc_id:
        acc = db.get(ChannelAccount, int(acc_id))
        old = decrypt_json(acc.config_enc)
        for k, v in cfg.items():
            if v or k not in old:
                old[k] = v
        acc.config_enc = encrypt_json(old)
        acc.status = "unverified"
    else:
        acc = ChannelAccount(platform=platform, name=form.get("name") or cls.label, config_enc=encrypt_json(cfg),
                             is_default=not db.query(ChannelAccount).filter_by(platform=platform).first())
        db.add(acc)
    db.flush()
    ok, msg = verify_account(db, acc)
    audit(db, user.username, "account_saved", f"account:{acc.id}", f"{platform} verify={ok} {msg}")
    db.commit()
    return back("/accounts")


@router.post("/accounts/{aid}/{action}")
def account_action(aid: int, action: str, db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    acc = db.get(ChannelAccount, aid)
    if action == "verify":
        verify_account(db, acc)
    elif action == "disable":
        acc.status = "disabled"
    elif action == "default":
        db.query(ChannelAccount).filter_by(platform=acc.platform).update({"is_default": False})
        acc.is_default = True
    elif action == "delete":
        db.delete(acc)
    audit(db, user.username, f"account_{action}", f"account:{aid}")
    db.commit()
    return back("/accounts")


# ------------------------------------------------------------------ users
@router.get("/users")
def users(request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    return render(request, db, user, "users.html", rows=db.query(User).order_by(User.id).all())


@router.post("/users")
def user_create(username: str = Form(...), password: str = Form(...), display_name: str = Form(""),
                role: str = Form("staff"), db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    if role not in ROLE_RANK or db.query(User).filter_by(username=username).first():
        raise HTTPException(400, "角色无效或用户名已存在")
    db.add(User(username=username.strip(), display_name=display_name, role=role, password_hash=hash_password(password)))
    audit(db, user.username, "user_created", f"user:{username}", role)
    db.commit()
    return back("/users")


@router.post("/users/{uid}/update")
def user_update(uid: int, role: str = Form(...), active: str = Form(""), password: str = Form(""),
                db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    u = db.get(User, uid)
    if u.id == user.id and (role != "admin" or active != "on"):
        raise HTTPException(400, "不能降低或停用自己的管理员账号")
    u.role, u.active = role, active == "on"
    if password:
        u.password_hash = hash_password(password)
    audit(db, user.username, "user_updated", f"user:{u.username}", f"role={role} active={u.active}")
    db.commit()
    return back("/users")


@router.post("/me/password")
def change_password(old: str = Form(...), new: str = Form(...), db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if not verify_password(old, user.password_hash) or len(new) < 6:
        raise HTTPException(400, "原密码错误或新密码少于6位")
    u = db.get(User, user.id)
    u.password_hash = hash_password(new)
    audit(db, user.username, "password_changed")
    db.commit()
    return back("/settings")


# ------------------------------------------------------------------ costs, logs, settings
@router.get("/costs")
def costs(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    by_purpose = db.query(CostRecord.purpose, func.count(), func.sum(CostRecord.units_in), func.sum(CostRecord.units_out),
                          func.sum(CostRecord.cost_usd)).group_by(CostRecord.purpose).all()
    by_day = db.query(func.date(CostRecord.created_at), func.sum(CostRecord.cost_usd)).group_by(
        func.date(CostRecord.created_at)).order_by(func.date(CostRecord.created_at).desc()).limit(31).all()
    searches = db.query(func.date(SearchRun.created_at), func.count()).group_by(func.date(SearchRun.created_at)).order_by(
        func.date(SearchRun.created_at).desc()).limit(31).all()
    return render(request, db, user, "costs.html", by_purpose=by_purpose, by_day=by_day, searches=searches,
                  budget=llm.budget_status(db))


@router.get("/logs")
def logs(request: Request, kind: str = "audit", db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    if kind == "system":
        rows = db.query(SystemLog).order_by(SystemLog.id.desc()).limit(500).all()
    elif kind == "jobs":
        rows = db.query(Job).order_by(Job.id.desc()).limit(300).all()
    else:
        rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(500).all()
    return render(request, db, user, "logs.html", rows=rows, kind=kind)


EDITABLE_SETTINGS = [
    ("outbound_enabled", "对外发送总开关", "bool"), ("sandbox_mode", "沙盒模式（所有邮件改发到测试邮箱）", "bool"),
    ("sandbox_address", "沙盒测试邮箱", "text"), ("daily_send_limit", "每日发送上限", "int"),
    ("min_hours_between_messages", "同一供应商最小发送间隔(小时)", "float"),
    ("company_name", "我方公司名称（开发信中使用）", "text"), ("company_signature", "邮件签名", "textarea"),
    ("inbox_poll_minutes", "收件检查间隔(分钟)", "float"), ("followup_check_minutes", "跟进检查间隔(分钟)", "float"),
    ("llm_enabled", "启用 LLM", "bool"), ("llm_base_url", "LLM 接口地址(OpenAI兼容)", "text"),
    ("llm_model", "LLM 模型", "text"), ("llm_price_in_per_1k", "输入单价 USD/1K tokens", "float"),
    ("llm_price_out_per_1k", "输出单价 USD/1K tokens", "float"), ("budget_daily_usd", "每日预算 USD", "float"),
    ("budget_monthly_usd", "每月预算 USD", "float"), ("search_max_queries_per_round", "每轮搜索关键词数", "int"),
    ("search_results_per_query", "每个关键词结果数", "int"), ("max_new_suppliers_per_round", "每轮最多新增供应商", "int"),
    ("pages_per_site", "每个网站采集页数", "int"), ("continuous_interval_hours", "持续任务轮次间隔(小时)", "float"),
]


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    backups = sorted(config.BACKUP_DIR.glob("backup_*.zip"), reverse=True)
    return render(request, db, user, "settings.html", st=settings.all_settings(db), fields=EDITABLE_SETTINGS,
                  has_key=bool(settings.get_secret(db, "llm_api_key")), backups=backups)


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    form = await request.form()
    for key, _, typ in EDITABLE_SETTINGS:
        raw = form.get(key)
        if typ == "bool":
            val = raw == "on"
        elif raw is None:
            continue
        elif typ == "int":
            val = int(raw)
        elif typ == "float":
            val = float(raw)
        else:
            val = raw
        settings.set_(db, key, val)
    if form.get("llm_api_key"):
        settings.set_secret(db, "llm_api_key", form.get("llm_api_key").strip())
    audit(db, user.username, "settings_saved", "settings",
          json.dumps({k: form.get(k) for k, _, _ in EDITABLE_SETTINGS}, ensure_ascii=False)[:3000])
    db.commit()
    return back("/settings")


# ------------------------------------------------------------------ export & backup
def _csv(rows: list[list], header: list[str], name: str) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename={name}"})


@router.get("/export/suppliers.csv")
def export_suppliers(db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    rows = []
    for s in db.query(Supplier).order_by(Supplier.id).all():
        emails = ";".join(c.value for c in s.contacts if c.ctype == "email")
        phones = ";".join(c.value for c in s.contacts if c.ctype in ("phone", "whatsapp"))
        rows.append([s.id, s.name, s.domain, s.website, s.country_hint, s.status, s.fit_category, s.fit_score,
                     s.risk_level, s.intent_level, s.intent_score, emails, phones, s.created_at])
    audit(db, user.username, "export_suppliers")
    db.commit()
    return _csv(rows, ["id", "名称", "域名", "官网", "国家", "状态", "符合度", "得分", "风险", "意向", "意向分", "邮箱",
                       "电话", "创建时间"], "suppliers.csv")


@router.get("/export/messages.csv")
def export_messages(db: Session = Depends(get_db), user: User = Depends(require("staff"))):
    rows = [[m.id, m.supplier_id, m.direction, m.kind, m.status, m.to_addr, m.actual_to_addr, m.from_addr, m.subject,
             m.body, m.created_at, m.sent_at, m.error] for m in db.query(Message).order_by(Message.id).all()]
    return _csv(rows, ["id", "供应商", "方向", "类型", "状态", "收件人", "实际收件(沙盒)", "发件人", "主题", "正文",
                       "创建", "发送", "错误"], "messages.csv")


@router.post("/backup")
def backup_now(db: Session = Depends(get_db), user: User = Depends(require("manager"))):
    from ..services.backup import create_backup

    path = create_backup()
    audit(db, user.username, "backup_created", path)
    db.commit()
    return back("/settings")


@router.get("/backups/{name}")
def backup_download(name: str, user: User = Depends(require("admin"))):
    p = config.BACKUP_DIR / name
    if not name.startswith("backup_") or "/" in name or "\\" in name or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=name)


@router.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")
