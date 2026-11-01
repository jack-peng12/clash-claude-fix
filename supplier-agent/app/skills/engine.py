"""Skill storage (versioned) and executable test runner."""

from __future__ import annotations

import copy

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Skill, SkillVersion
from ..services import rules as R
from .defaults import default_skills


def seed(db: Session) -> None:
    for sk in default_skills():
        if db.query(Skill).filter_by(key=sk["key"]).first():
            continue
        s = Skill(key=sk["key"], name=sk["name"], description=sk["description"], active_version=1)
        db.add(s)
        db.flush()
        db.add(SkillVersion(skill_id=s.id, version=1, content=sk["content"], note="初始版本（通用规则，待培训资料导入后确认）",
                            test_result=run_tests(sk["key"], sk["content"])))
    db.flush()


def get_content(db: Session, key: str) -> dict:
    s = db.query(Skill).filter_by(key=key).first()
    if s is None:
        for sk in default_skills():
            if sk["key"] == key:
                return copy.deepcopy(sk["content"])
        raise KeyError(key)
    v = db.query(SkillVersion).filter_by(skill_id=s.id, version=s.active_version).first()
    return copy.deepcopy(v.content)


def get_rules(db: Session, key: str) -> dict:
    return get_content(db, key).get("rules", {})


def criteria(db: Session) -> list[dict]:
    return get_rules(db, "screening").get("criteria", [])


def save_version(db: Session, key: str, content: dict, note: str, actor: str, activate: bool) -> SkillVersion:
    s = db.query(Skill).filter_by(key=key).one()
    latest = db.query(func.max(SkillVersion.version)).filter_by(skill_id=s.id).scalar() or 0
    v = SkillVersion(skill_id=s.id, version=latest + 1, content=content, note=note, created_by=actor)
    v.test_result = run_tests(key, content)
    db.add(v)
    db.flush()
    if activate:
        if not v.test_result.get("passed"):
            raise ValueError("新版本测试未全部通过，不能直接启用。可先保存为草稿再修正。")
        s.active_version = v.version
    return v


# ------------------------------- executable tests ---------------------------------------------


def _criteria_from(content: dict, fallback_key: str = "screening") -> list[dict]:
    if "criteria" in content.get("rules", {}):
        return content["rules"]["criteria"]
    for sk in default_skills():
        if sk["key"] == fallback_key:
            return sk["content"]["rules"]["criteria"]
    return []


def execute(key: str, content: dict, inp: dict) -> dict:
    rules = content.get("rules", {})
    if key == "search":
        from ..services.query_gen import template_queries

        if "url" in inp:
            ok, _ = R.is_relevant(inp["url"], inp.get("text", ""), rules)
            return {"relevant": ok}
        qs = template_queries(inp["spec"], rules, used=set())
        return {"queries": [q["query"] for q in qs]}
    if key == "screening":
        return R.screen(inp["relevant"], inp["levels"], inp["facts"], inp["risk"], rules)
    if key == "due_diligence":
        items = R.due_diligence(inp["facts"], rules, _criteria_from({}))
        return {"pending": [i["key"] for i in items]}
    if key == "outreach":
        if "check_text" in inp:
            return {"blocked": bool(R.check_forbidden(inp["check_text"], rules.get("forbidden_phrases", [])))}
        from ..services.outreach import render_initial

        subj, body = render_initial(rules, _criteria_from({}), inp["supplier_name"], "https://example.com",
                                    inp["country"], "", inp["questions"], {"company_name": "Test Co",
                                                                            "company_signature": "Regards"})
        return {"subject": subj, "body": body, "forbidden": R.check_forbidden(body, rules.get("forbidden_phrases", []))}
    if key == "inquiry":
        crit = _criteria_from({})
        ans = R.answered_keys(inp["reply"], crit)
        qstate = {k: {"answered": True} for k in list(ans.keys()) + inp.get("answered", [])}
        nxt = R.next_questions(inp["levels"], qstate, rules)
        return {"answered": list(ans.keys()), "next": nxt, "price_found": "price" in ans}
    if key == "followup":
        if "reply" in inp:
            return {"opt_out": R.is_opt_out(inp["reply"], rules.get("opt_out_patterns", []))}
        return R.followup_decision(inp, rules)
    if key == "risk":
        return R.detect_risk(inp["text"], rules.get("patterns", []))
    if key == "handoff":
        from .defaults import OPT_OUT_PATTERNS

        return R.compute_intent(inp["reply"], rules, _criteria_from({}), inp.get("required", []), OPT_OUT_PATTERNS)
    raise KeyError(key)


def _check(out: dict, expect: dict) -> list[str]:
    errs = []
    for k, v in expect.items():
        if k == "queries_contain":
            if not any(v.lower() in q.lower() for q in out.get("queries", [])):
                errs.append(f"关键词中缺少 '{v}'")
        elif k == "min_queries":
            if len(out.get("queries", [])) < v:
                errs.append(f"关键词数量 {len(out.get('queries', []))} < {v}")
        elif k == "pending_contains":
            if v not in out.get("pending", []):
                errs.append(f"待核验清单缺少 {v}")
        elif k == "pending_not_contains":
            if v in out.get("pending", []):
                errs.append(f"待核验清单不应包含 {v}")
        elif k == "body_contains":
            if v not in out.get("body", ""):
                errs.append(f"正文缺少 '{v}'")
        elif k == "no_forbidden":
            if out.get("forbidden"):
                errs.append(f"正文含越权表述 {out['forbidden']}")
        elif k == "answered_contains":
            if v not in out.get("answered", []):
                errs.append(f"未识别已回答 {v}")
        elif k == "next_contains":
            if v not in out.get("next", []):
                errs.append(f"下一步问题缺少 {v}")
        elif k == "next_not_contains":
            if v in out.get("next", []):
                errs.append(f"重复询问已回答问题 {v}")
        elif out.get(k) != v:
            errs.append(f"{k}: 期望 {v}，实际 {out.get(k)}")
    return errs


def run_tests(key: str, content: dict) -> dict:
    results = []
    for tc in content.get("test_cases", []):
        try:
            out = execute(key, content, tc["input"])
            errs = _check(out, tc.get("expect", {}))
        except Exception as e:  # a broken rule edit must show up as a failed test
            errs = [f"执行异常: {type(e).__name__}: {e}"]
        results.append({"name": tc.get("name", ""), "passed": not errs, "errors": errs})
    return {"passed": all(r["passed"] for r in results), "total": len(results),
            "failed": sum(1 for r in results if not r["passed"]), "results": results}
