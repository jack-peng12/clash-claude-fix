"""End-to-end business loop against a local fixture website and a real SMTP/IMAP server (GreenMail).

Start GreenMail first (see docs/TESTING.md); the test is skipped when it is not running.
"""

import imaplib
import smtplib
import uuid
from email.message import EmailMessage

import pytest

from app.db import session_scope
from app.models import ChannelAccount, Handoff, Message, ProcurementTask, Supplier, SupplierQuestion
from app.security import encrypt_json
from app.services import followup, inbox, messaging, pipeline, settings
from app.services.requirement_parser import parse_rules
from app.skills import engine as skills

from .conftest import greenmail_up

pytestmark = pytest.mark.skipif(not greenmail_up(), reason="GreenMail not running on 3025/3143")


def _supplier_send(frm: str, to: str, subject: str, body: str, in_reply_to: str) -> None:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = f"<{uuid.uuid4().hex}@supplier.test>"
    m["In-Reply-To"] = in_reply_to
    m["References"] = in_reply_to
    m.set_content(body)
    with smtplib.SMTP("127.0.0.1", 3025) as s:
        s.send_message(m)


def _mailbox_subjects(addr: str) -> list[str]:
    i = imaplib.IMAP4("127.0.0.1", 3143)
    i.login(addr, "x")
    i.select("INBOX")
    _, data = i.search(None, "ALL")
    out = []
    for num in (data[0] or b"").split():
        _, d = i.fetch(num, "(BODY[HEADER.FIELDS (SUBJECT)])")
        out.append(d[0][1].decode(errors="replace").strip())
    i.logout()
    return out


@pytest.fixture()
def env(fresh_db, fixture_sites, monkeypatch):
    run = uuid.uuid4().hex[:8]
    agent = f"agent-{run}@buyer.test"
    sandbox = f"supplier-{run}@supplier.test"
    with session_scope() as db:
        settings.set_(db, "sandbox_mode", True)
        settings.set_(db, "sandbox_address", sandbox)
        settings.set_(db, "min_hours_between_messages", 0)
        db.add(ChannelAccount(platform="email", name="测试邮箱", is_default=True, status="active", config_enc=encrypt_json({
            "from_addr": agent, "from_name": "Buyer", "smtp_host": "127.0.0.1", "smtp_port": "3025",
            "smtp_security": "none", "imap_host": "127.0.0.1", "imap_port": "3143", "imap_security": "none",
            "username": agent, "password": "x"})))
        spec = parse_rules("找2家英国现成公司，必须带VAT和企业银行账户，董事待确认", skills.criteria(db))
        spec["target_suppliers"] = 2
        t = ProcurementTask(title="英国测试", raw_text="", spec=spec, auto_outreach=True, status="queued")
        db.add(t)
        db.flush()
        tid = t.id
    results = [{"url": fixture_sites["acme"], "title": "Acme UK shelf companies", "snippet": ""},
               {"url": fixture_sites["risky"], "title": "FastCo", "snippet": ""},
               {"url": "https://www.facebook.com/shelf", "title": "fb", "snippet": ""}]
    monkeypatch.setattr(pipeline, "search", lambda q, n, region="wt-wt": results)
    return {"tid": tid, "agent": agent, "sandbox": sandbox}


def test_full_loop(env):
    pipeline.run_round(env["tid"])

    with session_scope() as db:
        sups = {s.domain: s for s in db.query(Supplier).all()}
        assert set(sups) == {"127.0.0.1", "localhost"}, "facebook must be blocked, two suppliers filed"
        acme, risky = sups["127.0.0.1"], sups["localhost"]
        assert acme.name == "Acme Formations Ltd"
        assert acme.fit_category == "insufficient", acme.assessment  # bank account only 'can be arranged'
        assert risky.fit_category == "high_risk"
        emails = {c.normalized for c in acme.contacts if c.ctype == "email"}
        assert "sales@acme-formations.test" in emails
        assert any(c.ctype == "whatsapp" for c in acme.contacts)
        assert all(c.evidence_id for c in acme.contacts), "every contact must point to saved evidence"
        assert {f.currency for f in acme.facts if f.key == "price"} == {"GBP"}
        assert all(f.status == "web_claim" for f in acme.facts)
        initial = db.query(Message).filter_by(supplier_id=acme.id, kind="initial").one()
        assert initial.status == "queued" and "Acme Formations Ltd" in initial.body
        assert not db.query(Message).filter_by(supplier_id=risky.id).first(), "high-risk supplier is not contacted"
        acme_id, initial_id = acme.id, initial.id

    with session_scope() as db:
        assert messaging.deliver(db, initial_id) == "sent"
        # duplicate initial is blocked
        dup = Message(supplier_id=acme_id, channel="email", direction="out", kind="initial", subject="x", body="x",
                      to_addr="sales@acme-formations.test", created_by="ai")
        db.add(dup)
        db.flush()
        ok, why = messaging.queue(db, dup)
        assert not ok and "重复" in why
        sent = db.get(Message, initial_id)
        assert sent.actual_to_addr == env["sandbox"]
        mid = sent.header_message_id
    assert any("Acme" in s for s in _mailbox_subjects(env["sandbox"])), "mail really arrived in the test mailbox"

    # Supplier answers VAT only -> AI should ask the still-open bank account question, not VAT again.
    _supplier_send(env["sandbox"], env["agent"], "Re: enquiry",
                   "Hello, yes the company is VAT registered. What else do you need?\n\n> Is the company VAT registered?",
                   mid)
    with session_scope() as db:
        assert inbox.poll_all(db)["messages"] == 1
    with session_scope() as db:
        inbound = db.query(Message).filter_by(direction="in", supplier_id=acme_id).one()
        assert inbound.analysis["action"] == "clarify_queued", inbound.analysis
        clar = db.query(Message).filter_by(kind="clarify", supplier_id=acme_id).one()
        assert "bank account" in clar.body.lower() and "vat registered" not in clar.body.lower()
        q = db.query(SupplierQuestion).filter_by(supplier_id=acme_id, key="vat_registered").one()
        assert q.answered
        assert messaging.deliver(db, clar.id) == "sent"
        clar_mid = db.get(Message, clar.id).header_message_id

    # Supplier confirms stock + price -> handoff, AI stops.
    _supplier_send(env["sandbox"], env["agent"], "Re: Re: enquiry",
                   "We currently have 2 UK companies available with a business bank account. "
                   "Price is GBP 2,950 each. Happy to proceed.", clar_mid)
    with session_scope() as db:
        inbox.poll_all(db)
    with session_scope() as db:
        sup = db.get(Supplier, acme_id)
        assert sup.taken_over and sup.status == "human_takeover" and sup.intent_level == "high"
        h = db.query(Handoff).filter_by(supplier_id=acme_id).one()
        assert "provided_price" in h.triggered
        ai_msg = Message(supplier_id=acme_id, channel="email", direction="out", kind="followup", subject="ping",
                         body="ping", to_addr="sales@acme-formations.test", created_by="ai")
        db.add(ai_msg)
        db.flush()
        ok, why = messaging.queue(db, ai_msg)
        assert not ok and "人工接管" in why
        assert followup.run(db)["queued"] == 0
        human = Message(supplier_id=acme_id, channel="email", direction="out", kind="manual", subject="Re: offer",
                        body="Thanks, I will review.", to_addr="sales@acme-formations.test",
                        created_by="user:admin", dedupe_key="manual:1")
        db.add(human)
        db.flush()
        assert messaging.queue(db, human)[0], "employee can still write after takeover"


def test_opt_out_stops_everything(env):
    pipeline.run_round(env["tid"])
    with session_scope() as db:
        acme = db.query(Supplier).filter_by(domain="127.0.0.1").one()
        initial = db.query(Message).filter_by(supplier_id=acme.id, kind="initial").one()
        messaging.deliver(db, initial.id)
        mid, sid = initial.header_message_id, acme.id
    _supplier_send(env["sandbox"], env["agent"], "Re: enquiry", "Not interested, please do not contact us again.", mid)
    with session_scope() as db:
        inbox.poll_all(db)
    with session_scope() as db:
        s = db.get(Supplier, sid)
        assert s.opted_out and s.status == "opted_out"
        assert not db.query(Message).filter_by(supplier_id=sid, kind="clarify").first()
        s.last_outbound_at = s.last_outbound_at.replace(year=2000)
        assert followup.run(db)["queued"] == 0


def test_followup_after_silence_and_pause_cancel(env):
    pipeline.run_round(env["tid"])
    with session_scope() as db:
        acme = db.query(Supplier).filter_by(domain="127.0.0.1").one()
        initial = db.query(Message).filter_by(supplier_id=acme.id, kind="initial").one()
        messaging.deliver(db, initial.id)
        acme.last_outbound_at = acme.last_outbound_at.replace(year=2000)
        db.get(Message, initial.id).sent_at = acme.last_outbound_at
    with session_scope() as db:
        assert followup.run(db)["queued"] == 1
        fu = db.query(Message).filter_by(kind="followup").one()
        assert messaging.deliver(db, fu.id) == "sent"
        assert db.get(Supplier, fu.supplier_id).followup_count == 1
    with session_scope() as db:
        t = db.get(ProcurementTask, env["tid"])
        t.status = "paused"
    rounds_before = None
    with session_scope() as db:
        rounds_before = db.get(ProcurementTask, env["tid"]).rounds_done
    pipeline.run_round(env["tid"])
    with session_scope() as db:
        assert db.get(ProcurementTask, env["tid"]).rounds_done == rounds_before, "paused task must not run"


def test_send_failure_retries_then_fails(env, monkeypatch):
    pipeline.run_round(env["tid"])
    with session_scope() as db:
        acc = db.query(ChannelAccount).one()
        acc.config_enc = encrypt_json({"from_addr": env["agent"], "smtp_host": "127.0.0.1", "smtp_port": "1",
                                       "smtp_security": "none"})
        msg = db.query(Message).filter_by(kind="initial").first()
        mid = msg.id
    outcomes = []
    for _ in range(4):
        with session_scope() as db:
            m = db.get(Message, mid)
            if m.status != "queued":
                break
            outcomes.append(messaging.deliver(db, mid))
    assert outcomes[:3] == ["retry", "retry", "retry"] and outcomes[-1] == "failed"
    with session_scope() as db:
        m = db.get(Message, mid)
        assert m.status == "failed" and m.error
