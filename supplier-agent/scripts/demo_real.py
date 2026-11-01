"""Reproducible real-world demo.

REAL:      web search, supplier website fetching, evidence, extraction, screening, email composition,
           SMTP delivery and IMAP reading against a controlled mailbox.
CONTROLLED: sandbox mode is forced ON, so every email goes to the test mailbox instead of the real
           supplier. The supplier replies are written by this script (playing the supplier) and sent
           over SMTP into the agent mailbox; they are clearly labelled as simulated in the report.

Usage (GreenMail or any SMTP/IMAP test mailbox must be reachable):
    SA_DATA_DIR=/tmp/sa_demo python scripts/demo_real.py --country 英国 --out docs/demo_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SA_RUN_WORKER", "0")

from app.db import session_scope  # noqa: E402
from app.main import bootstrap  # noqa: E402
from app.models import (  # noqa: E402
    ChannelAccount,
    Contact,
    Evidence,
    Fact,
    Handoff,
    Message,
    ProcurementTask,
    SearchRun,
    Supplier,
    SupplierTask,
)
from app.security import encrypt_json  # noqa: E402
from app.services import inbox, messaging, pipeline, settings  # noqa: E402
from app.services.requirement_parser import parse  # noqa: E402
from app.skills import engine as skills  # noqa: E402


def supplier_reply(smtp_host, smtp_port, frm, to, subject, body, in_reply_to):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Message-ID"] = f"<{uuid.uuid4().hex}@demo-supplier.test>"
    m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.send_message(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="英国")
    ap.add_argument("--smtp-host", default="127.0.0.1")
    ap.add_argument("--smtp-port", default="3025")
    ap.add_argument("--imap-port", default="3143")
    ap.add_argument("--queries", type=int, default=4)
    ap.add_argument("--max-new", type=int, default=8)
    ap.add_argument("--currency", default="GBP")
    ap.add_argument("--out", default="docs/demo_report.md")
    a = ap.parse_args()

    bootstrap()
    run = uuid.uuid4().hex[:6]
    agent, sandbox = f"agent-{run}@buyer.test", f"sandbox-{run}@buyer.test"
    requirement = (f"找5家{a.country}现成公司供应商，必须带VAT和企业银行账户，董事待确认，"
                   f"是否注册过亚马逊需确认，预算每家5000以内")
    with session_scope() as db:
        settings.set_(db, "sandbox_mode", True)
        settings.set_(db, "sandbox_address", sandbox)
        settings.set_(db, "min_hours_between_messages", 0)
        settings.set_(db, "search_max_queries_per_round", a.queries)
        settings.set_(db, "max_new_suppliers_per_round", a.max_new)
        settings.set_(db, "company_name", "Demo Cross-border Trading Co.")
        db.add(ChannelAccount(platform="email", name="演示邮箱", is_default=True, status="active",
                              config_enc=encrypt_json({
                                  "from_addr": agent, "from_name": "Procurement", "smtp_host": a.smtp_host,
                                  "smtp_port": a.smtp_port, "smtp_security": "none", "imap_host": a.smtp_host,
                                  "imap_port": a.imap_port, "imap_security": "none", "username": agent,
                                  "password": "x"})))
        spec = parse(db, requirement, skills.criteria(db))
        spec["target_suppliers"] = 5
        task = ProcurementTask(title=f"演示：{a.country}现成公司", raw_text=requirement, spec=spec, auto_outreach=True,
                               status="queued")
        db.add(task)
        db.flush()
        tid = task.id

    t0 = time.time()
    pipeline.run_round(tid)
    collect_secs = time.time() - t0

    with session_scope() as db:
        queued = [m.id for m in db.query(Message).filter_by(status="queued").all()]
    for mid in queued:
        with session_scope() as db:
            messaging.deliver(db, mid)

    convo = {}
    with session_scope() as db:
        first = db.query(Message).filter_by(kind="initial", status="sent").order_by(Message.id).first()
        if first:
            convo = {"supplier_id": first.supplier_id, "mid": first.header_message_id, "subject": first.subject}
    if convo:
        supplier_reply(a.smtp_host, int(a.smtp_port), sandbox, agent, "Re: " + convo["subject"],
                       "Hi, thanks for reaching out. Yes, our companies are VAT registered. "
                       "Let me know what else you need.", convo["mid"])
        with session_scope() as db:
            inbox.poll_all(db)
        with session_scope() as db:
            clar = db.query(Message).filter_by(supplier_id=convo["supplier_id"], kind="clarify").first()
            if clar and clar.status == "queued":
                messaging.deliver(db, clar.id)
                convo["clar_mid"] = db.get(Message, clar.id).header_message_id
        if convo.get("clar_mid"):
            supplier_reply(a.smtp_host, int(a.smtp_port), sandbox, agent, "Re: " + convo["subject"],
                           "We currently have 3 companies available, each with a business bank account. "
                           f"Price is {a.currency} 2,400 per company. Happy to proceed.", convo["clar_mid"])
            with session_scope() as db:
                inbox.poll_all(db)
        with session_scope() as db:
            probe = Message(supplier_id=convo["supplier_id"], channel="email", direction="out", kind="followup",
                            subject="AI probe after takeover", body="probe", to_addr="x@example.com", created_by="ai")
            db.add(probe)
            db.flush()
            convo["probe_allowed"], convo["probe_reason"] = messaging.queue(db, probe)

    write_report(tid, requirement, collect_secs, convo, a.out)
    print("report written to", a.out)


def write_report(tid, requirement, secs, convo, out):
    L = []
    with session_scope() as db:
        task = db.get(ProcurementTask, tid)
        L += ["# 真实业务演示报告", "", f"- 生成时间（UTC）：{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}",
              f"- 采购需求（员工输入）：{requirement}",
              f"- 解析结果：国家 {[c['name'] for c in task.spec['countries']]}，条件 "
              f"`{json.dumps(task.spec['levels'], ensure_ascii=False)}`，解析方式 {task.spec.get('parser')}",
              f"- 搜索+采集+筛选耗时：{secs:.0f} 秒；任务统计：`{json.dumps(task.stats, ensure_ascii=False)}`", "",
              "## 1. 真实搜索关键词与结果", "", "| 关键词 | 语言 | 来源 | 状态 | 结果数 | 相关 | 新供应商 |", "|---|---|---|---|---|---|---|"]
        for r in db.query(SearchRun).filter_by(task_id=tid):
            L.append(f"| {r.query} | {r.lang} | {r.origin} | {r.status} | {r.result_count} | {r.relevant_count} | {r.new_suppliers} |")
        L += ["", "## 2. 真实找到并建档的供应商", "",
              "| # | 名称 | 域名 | 国家识别 | 符合度 | 得分 | 风险 | 邮箱 | 其他联系方式 | 网页证据数 | 事实条目 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for st, s in db.query(SupplierTask, Supplier).join(Supplier, Supplier.id == SupplierTask.supplier_id).filter(
                SupplierTask.task_id == tid):
            emails = ", ".join(c.value for c in s.contacts if c.ctype == "email")
            other = ", ".join(sorted({c.ctype for c in s.contacts if c.ctype != "email"}))
            ev = db.query(Evidence).filter_by(supplier_id=s.id).count()
            facts = db.query(Fact).filter_by(supplier_id=s.id).count()
            L.append(f"| {s.id} | {s.name} | {s.domain} | {s.country_hint} | {s.fit_category} | {s.fit_score} | "
                     f"{s.risk_level} | {emails} | {other} | {ev} | {facts} |")
        L += ["", "### 判定原因", ""]
        for s in db.query(Supplier).join(SupplierTask, SupplierTask.supplier_id == Supplier.id).filter(
                SupplierTask.task_id == tid):
            L.append(f"- **{s.name}**（{s.domain}）：{s.assessment.get('reason', '')}")
        sample = db.query(Fact).join(Supplier).filter(Fact.evidence_id.isnot(None)).limit(8).all()
        L += ["", "### 证据样例（事实 → 网页证据，可在后台点开原始HTML核对）", ""]
        for f in sample:
            e = db.get(Evidence, f.evidence_id)
            L.append(f"- `{f.key}`={f.polarity}（{f.status}）← {e.final_url or e.url} sha256 `{e.sha256[:16]}` "
                     f"采集于 {e.fetched_at:%Y-%m-%d %H:%M} UTC：“{f.snippet[:140]}”")
        fails = [e for e in db.query(Evidence).filter(Evidence.error != "").all()]
        if fails:
            L += ["", "### 采集失败记录（如实记录）", ""]
            L += [f"- {e.url}：{e.error[:150]}" for e in fails[:15]]
        L += ["", "## 3. 自动建联（沙盒：真实 SMTP 发出，收件人被替换为测试邮箱）", "",
              "| 消息 | 供应商 | 类型 | 原收件人 | 实际收件 | 状态 | 原因 |", "|---|---|---|---|---|---|---|"]
        for m in db.query(Message).filter(Message.direction == "out").order_by(Message.id):
            L.append(f"| {m.id} | {m.supplier_id} | {m.kind} | {m.to_addr} | {m.actual_to_addr} | {m.status} | {m.error[:80]} |")
        first = db.query(Message).filter_by(kind="initial", status="sent").first()
        if first:
            L += ["", "### 首封开发信示例", "", "```", f"Subject: {first.subject}", "", first.body, "```"]
        if convo:
            L += ["", "## 4. 回复处理（供应商回复由演示脚本模拟，经真实 SMTP/IMAP 往返）", ""]
            for m in db.query(Message).filter_by(supplier_id=convo["supplier_id"]).order_by(Message.id):
                if m.direction == "in":
                    L.append(f"- 来信 #{m.id}：“{m.body.strip()[:160]}” → AI 动作 **{m.analysis.get('action')}**"
                             f"{'，' + m.analysis['reason'] if m.analysis.get('reason') else ''}，意向分 {m.analysis.get('intent', {}).get('score')}")
                elif m.kind == "clarify":
                    L += ["", "AI 追问（只问未回答的问题）：", "", "```", m.body, "```", ""]
            h = db.query(Handoff).filter_by(supplier_id=convo["supplier_id"]).first()
            sup = db.get(Supplier, convo["supplier_id"])
            L += ["", f"- 转人工：{'是' if h else '否'}；原因：{h.reason if h else ''}；供应商状态：{sup.status}",
                  f"- 接管后 AI 尝试发送被拦截：{'是' if not convo.get('probe_allowed') else '否'}（{convo.get('probe_reason')}）"]
        L += ["", "## 5. 本演示的真实性边界", "",
              "- 真实：搜索引擎结果、供应商网站内容、网页证据文件、联系方式、筛选结果、SMTP 发送与 IMAP 读取。",
              "- 受控：沙盒模式开启，没有任何邮件发送给真实供应商；供应商回复为脚本模拟。",
              "- 未验证：真实供应商的真实回复、真实邮箱服务商（Gmail/Outlook/企业邮箱）的投递率与反垃圾表现。"]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
