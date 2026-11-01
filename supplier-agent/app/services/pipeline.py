"""One round of a procurement task: search -> collect -> dedupe -> screen -> outreach."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Evidence, Job, ManualAction, Message, ProcurementTask, SearchRun, Supplier, SupplierTask, utcnow
from ..skills import engine as skills
from . import fetcher, messaging, outreach, query_gen
from . import rules as R
from . import settings
from . import suppliers as S
from .extractor import company_name, extract_contacts, registered_domain
from .logs import audit, notify, syslog
from .search import SearchError, search


class Stop(Exception):
    pass


def _check_status(task_id: int) -> None:
    with session_scope() as s:
        st = s.get(ProcurementTask, task_id).status
    if st in ("paused", "cancelled"):
        raise Stop(st)


def _bump(db: Session, task: ProcurementTask, **kw) -> None:
    stats = dict(task.stats or {})
    for k, v in kw.items():
        stats[k] = stats.get(k, 0) + v
    task.stats = stats


def collect_site(db: Session, url: str, task: ProcurementTask, query: str, pages_per_site: int) -> dict:
    """Fetch homepage + relevant subpages of one candidate site and file the supplier."""
    p = urlparse(url)
    home = f"{p.scheme}://{p.netloc}/"
    domain = registered_domain(home)
    criteria = skills.criteria(db)
    search_rules = skills.get_rules(db, "search")
    risk_rules = skills.get_rules(db, "risk").get("patterns", [])

    pages = []
    first = fetcher.fetch(url)
    pages.append(first)
    if url.rstrip("/") != home.rstrip("/"):
        pages.append(fetcher.fetch(home))
    base = next((pg for pg in pages if pg.ok), None)
    if base is None:
        err = "; ".join(f"{pg.url}: {pg.error or pg.status}" for pg in pages)
        return {"status": "fetch_failed", "domain": domain, "error": err}
    for sub in fetcher.pick_subpages(base, pages_per_site):
        if len(pages) >= pages_per_site + 1:
            break
        if sub.rstrip("/") not in {pg.url.rstrip("/") for pg in pages}:
            pages.append(fetcher.fetch(sub))
    ok_pages = [pg for pg in pages if pg.ok]
    all_text = "\n\n".join(pg.text for pg in ok_pages)
    relevant, hits = R.is_relevant(url, all_text, search_rules)
    contacts = []
    for pg in ok_pages:
        for c in extract_contacts(pg.html, pg.text):
            c["source_url"] = pg.final_url or pg.url
            contacts.append(c)

    sup = S.find_existing(db, domain, contacts)
    is_new = sup is None
    if is_new:
        if not relevant:
            return {"status": "irrelevant", "domain": domain, "hits": hits}
        sup = Supplier(domain=domain, website=home, name=company_name(base.html, base.title, domain),
                       source_channel="web")
        db.add(sup)
        db.flush()
        audit(db, "ai", "supplier_created", f"supplier:{sup.id}", f"{domain} via '{query}'")
    if not db.query(SupplierTask).filter_by(supplier_id=sup.id, task_id=task.id).first():
        db.add(SupplierTask(supplier_id=sup.id, task_id=task.id, found_by_query=query))

    for pg in pages:
        ev_files = fetcher.save_evidence(pg, sup.id)
        ev = Evidence(supplier_id=sup.id, url=pg.url, final_url=pg.final_url, http_status=pg.status, title=pg.title,
                      excerpt=pg.text[:1500], error=pg.error, **ev_files)
        db.add(ev)
        db.flush()
        if not pg.ok:
            continue
        S.add_contacts(db, sup, [c for c in contacts if c["source_url"] == (pg.final_url or pg.url)],
                       pg.final_url or pg.url, ev.id)
        for key, d in R.detect_criteria(pg.text, criteria).items():
            if key == "price":
                for pr in d.get("prices", [])[:5]:
                    S.add_fact(db, sup, "price", "yes", "web_claim", pr["snippet"], evidence_id=ev.id,
                               amount=pr["amount"], currency=pr["currency"], value=f"{pr['currency']} {pr['amount']:,.0f}")
            else:
                S.add_fact(db, sup, key, d["polarity"], "web_claim", d["snippet"], evidence_id=ev.id)
    countries = S.country_mentioned(all_text, domain, task.spec)
    if countries:
        sup.country_hint = ",".join(sorted(set(filter(None, sup.country_hint.split(","))) | set(countries)))
    if not sup.description:
        sup.description = (base.text or "")[:1500]
    risk = R.detect_risk(all_text, risk_rules)
    if risk["level"] == "high":
        sup.risk_level = "high"
    res = S.screen_supplier(db, sup, task, all_text)
    return {"status": "new" if is_new else "existing", "supplier_id": sup.id, "category": res["category"],
            "domain": domain}


def plan_outreach(db: Session, sup: Supplier, task: ProcurementTask) -> str:
    contact_cats = skills.get_rules(db, "screening").get("contact_categories", ["match", "insufficient"])
    if sup.fit_category not in contact_cats:
        return "not_eligible"
    if sup.taken_over or sup.opted_out:
        return "blocked"
    if db.query(Message).filter(Message.supplier_id == sup.id, Message.direction == "out",
                                Message.kind == "initial").first():
        return "already"
    msg = outreach.compose_initial(db, sup, task)
    if msg is None:
        if not db.query(ManualAction).filter_by(supplier_id=sup.id, action="contact").first():
            other = [c for c in sup.contacts if c.ctype in ("form", "phone", "whatsapp", "telegram")]
            db.add(ManualAction(platform="web", action="contact", supplier_id=sup.id, task_id=task.id,
                                target=", ".join(f"{c.ctype}:{c.value}" for c in other) or sup.website,
                                content="未找到公开邮箱，请通过联系表单/电话联系并询价。"))
        return "manual"
    if task.auto_outreach:
        ok, reason = messaging.queue(db, msg)
        return "queued" if ok else f"blocked:{reason}"
    return "draft"


def run_round(task_id: int) -> None:
    with session_scope() as db:
        task = db.get(ProcurementTask, task_id)
        if task.status in ("paused", "cancelled", "completed"):
            return
        task.status, task.last_error = "running", ""
        task.rounds_done += 1
        round_no = task.rounds_done
        st = settings.all_settings(db)
        queries = query_gen.next_queries(db, task.id, task.spec, skills.get_rules(db, "search"),
                                         int(st["search_max_queries_per_round"]))
        for q in queries:
            db.add(SearchRun(task_id=task.id, round_no=round_no, query=q["query"], lang=q["lang"], origin=q["origin"]))
        audit(db, "ai", "round_started", f"task:{task.id}", f"round {round_no}, {len(queries)} queries")
    if not queries:
        with session_scope() as db:
            task = db.get(ProcurementTask, task_id)
            task.status = "completed"
            notify(db, f"任务“{task.title}”已无新关键词可用", "请补充需求或关键词模板后重新启动。", f"/tasks/{task.id}", "warning")
        return

    new_total = 0
    max_new = int(st["max_new_suppliers_per_round"])
    try:
        with session_scope() as db:
            run_ids = [r.id for r in db.query(SearchRun).filter_by(task_id=task_id, round_no=round_no, status="pending")]
        seen_domains: set[str] = set()
        for rid in run_ids:
            _check_status(task_id)
            with session_scope() as db:
                run = db.get(SearchRun, rid)
                run.status = "running"
                query = run.query
            try:
                results = search(query, int(st["search_results_per_query"]), region=st.get("search_region", "wt-wt"))
                err = ""
            except SearchError as e:
                results, err = [], str(e)
            with session_scope() as db:
                run = db.get(SearchRun, rid)
                run.result_count = len(results)
                run.status, run.error = ("failed", err) if err else ("done", "")
                search_rules = skills.get_rules(db, "search")
                annotated = []
                for r in results:
                    ok, hits = R.is_relevant(r["url"], f"{r['title']} {r['snippet']}", search_rules)
                    annotated.append({**r, "relevant": ok, "hits": hits})
                run.results = annotated
                run.relevant_count = sum(1 for r in annotated if r["relevant"])
            if err:
                continue
            new_here = 0
            for r in annotated:
                _check_status(task_id)
                if new_total >= max_new:
                    break
                dom = registered_domain(r["url"])
                if R.is_blocked(r["url"], search_rules) or dom in seen_domains:
                    continue
                seen_domains.add(dom)
                with session_scope() as db:
                    if db.query(SupplierTask).join(Supplier).filter(Supplier.domain == dom,
                                                                    SupplierTask.task_id == task_id).first():
                        continue
                    task = db.get(ProcurementTask, task_id)
                    try:
                        res = collect_site(db, r["url"], task, query, int(st["pages_per_site"]))
                    except Exception as e:
                        syslog("ERROR", "collect", f"{r['url']}: {type(e).__name__}: {e}")
                        _bump(db, task, collect_errors=1)
                        continue
                    if res["status"] == "fetch_failed":
                        _bump(db, task, fetch_failed=1)
                        syslog("WARNING", "collect", f"采集失败 {res['domain']}: {res['error'][:300]}")
                        continue
                    if res["status"] == "irrelevant":
                        _bump(db, task, irrelevant=1)
                        continue
                    sup = db.get(Supplier, res["supplier_id"])
                    outcome = plan_outreach(db, sup, task)
                    _bump(db, task, **{f"cat_{res['category']}": 1, f"outreach_{outcome.split(':')[0]}": 1})
                    if res["status"] == "new":
                        new_here += 1
                        new_total += 1
                        _bump(db, task, suppliers_new=1)
            with session_scope() as db:
                db.get(SearchRun, rid).new_suppliers = new_here
    except Stop as s:
        with session_scope() as db:
            db.query(SearchRun).filter_by(task_id=task_id, status="pending").update({"status": "skipped"})
            db.query(SearchRun).filter_by(task_id=task_id, status="running").update({"status": "stopped"})
            audit(db, "system", "round_stopped", f"task:{task_id}", str(s))
        return

    with session_scope() as db:
        task = db.get(ProcurementTask, task_id)
        found = db.query(SupplierTask).filter_by(task_id=task_id).filter(
            SupplierTask.fit_category.in_(["match", "insufficient"])).count()
        target = int(task.spec.get("target_suppliers", 20))
        audit(db, "ai", "round_finished", f"task:{task_id}", f"round {round_no}: new={new_total}, eligible={found}")
        if task.status != "running":
            return
        if found >= target and not task.continuous:
            task.status = "completed"
            notify(db, f"任务“{task.title}”已达到目标", f"可联系供应商 {found} 家。", f"/tasks/{task_id}", "success")
        elif task.continuous or found < target:
            hours = float(st["continuous_interval_hours"]) if (task.continuous and found >= target) else 0.05
            db.add(Job(jtype="task_round", payload={"task_id": task_id}, run_after=utcnow() + timedelta(hours=hours)))
            if round_no >= 20 and not task.continuous:
                task.status = "completed"
