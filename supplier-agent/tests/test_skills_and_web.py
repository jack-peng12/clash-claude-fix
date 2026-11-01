import copy

import pytest
from fastapi.testclient import TestClient

from app.db import session_scope
from app.models import Skill, Supplier, User
from app.security import hash_password
from app.skills import engine as skills
from app.skills.defaults import default_skills


@pytest.mark.parametrize("sk", default_skills(), ids=lambda s: s["key"])
def test_every_default_skill_is_complete_and_passes(sk):
    c = sk["content"]
    for field in ("inputs", "outputs", "rules", "decision_rules", "sources", "boundaries", "exceptions", "test_cases"):
        assert c.get(field), f"{sk['key']} missing {field}"
    assert skills.run_tests(sk["key"], c)["passed"]


def test_skill_versioning_blocks_broken_rules(db):
    content = skills.get_content(db, "handoff")
    broken = copy.deepcopy(content)
    broken["rules"]["handoff_threshold"] = 1  # "contract" alone would now trigger handoff
    broken["rules"]["hard_combos"] = []
    with pytest.raises(ValueError):
        skills.save_version(db, "handoff", broken, "bad edit", "tester", activate=True)
    db.rollback()
    v = skills.save_version(db, "handoff", broken, "draft only", "tester", activate=False)
    assert not v.test_result["passed"]
    assert db.query(Skill).filter_by(key="handoff").one().active_version == 1

    better = copy.deepcopy(content)
    better["rules"]["handoff_threshold"] = 55
    v3 = skills.save_version(db, "handoff", better, "lower threshold", "tester", activate=True)
    assert db.query(Skill).filter_by(key="handoff").one().active_version == v3.version
    assert skills.get_rules(db, "handoff")["handoff_threshold"] == 55


def test_web_negative_needs_supplier_confirmation(db):
    from app.models import ProcurementTask
    from app.services import suppliers as S

    t = ProcurementTask(title="t", spec={"countries": [], "levels": {"inventory": "required",
                                                                       "vat_registered": "required"}})
    s = Supplier(name="X", domain="x.test", website="https://x.test", description="uk shelf companies for sale")
    db.add_all([t, s])
    db.flush()
    S.add_fact(db, s, "inventory", "yes", "web_claim", "shelf companies")
    S.add_fact(db, s, "vat_registered", "no", "web_claim", "sold without VAT")
    assert S.screen_supplier(db, s, t)["category"] == "insufficient"
    S.add_fact(db, s, "vat_registered", "no", "supplier_claim", "No, none of our companies has VAT")
    assert S.screen_supplier(db, s, t)["category"] == "no_match"
    with pytest.raises(ValueError):
        S.add_fact(db, s, "vat_registered", "yes", "human_verified", "AI must not do this")


@pytest.fixture()
def client(fresh_db):
    from app.main import app

    with session_scope() as s:
        s.add(User(username="viewer", role="viewer", password_hash=hash_password("pw123456")))
        s.add(User(username="staff", role="staff", password_hash=hash_password("pw123456")))
        s.add(Supplier(name="Demo", domain="demo.test", website="https://demo.test"))
    with TestClient(app) as c:
        yield c


def _login(c, u, p="pw123456"):
    r = c.post("/login", data={"username": u, "password": p}, follow_redirects=False)
    assert r.status_code == 303


def test_login_required(client):
    r = client.get("/suppliers", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.post("/login", data={"username": "staff", "password": "wrong"}).text.count("错误") >= 1


def test_roles(client):
    _login(client, "viewer")
    assert client.get("/suppliers").status_code == 200
    assert client.post("/suppliers/1/takeover").status_code == 403
    assert client.get("/users").status_code == 403
    client.get("/logout")
    _login(client, "staff")
    assert client.post("/suppliers/1/takeover", follow_redirects=False).status_code == 303
    with session_scope() as s:
        assert s.get(Supplier, 1).taken_over
    assert client.post("/suppliers/1/release").status_code == 403  # only manager can hand back to AI
    assert client.post("/skills/handoff/save", data={"content": "{}"}).status_code == 403
    client.get("/logout")
    _login(client, "admin", "admin123")
    assert client.post("/suppliers/1/release", follow_redirects=False).status_code == 303
    with session_scope() as s:
        assert not s.get(Supplier, 1).taken_over


def test_all_pages_render(client):
    _login(client, "admin", "admin123")
    for p in ["/", "/tasks", "/tasks/new", "/suppliers", "/suppliers/1", "/handoffs", "/messages", "/quotes",
              "/manual", "/skills", "/skills/screening", "/accounts", "/users", "/costs", "/logs", "/logs?kind=system",
              "/logs?kind=jobs", "/settings", "/export/suppliers.csv", "/export/messages.csv"]:
        assert client.get(p).status_code == 200, p


def test_create_task_from_chinese_text(client):
    _login(client, "staff")
    r = client.post("/tasks/parse", data={"raw_text": "德国GmbH现成公司，必须有VAT，董事最好能继续任职"})
    assert r.status_code == 200 and "Germany" in r.text
    form = {"title": "德国测试", "countries": "德国", "company_types": "GmbH", "target_suppliers": "5",
            "spec_json": "{}", "level_vat_registered": "required", "level_director_continue": "preferred"}
    r = client.post("/tasks", data=form, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "德国测试" in page


def test_backup_roundtrip(fresh_db, tmp_path):
    from app.services.backup import create_backup

    path = create_backup()
    import zipfile

    with zipfile.ZipFile(path) as z:
        assert "supplier_agent.db" in z.namelist() and "secret.key" in z.namelist()
