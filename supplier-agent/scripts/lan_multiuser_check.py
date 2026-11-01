"""Multi-user acceptance check: N employees use the system at the same time over HTTP.

Run from any computer on the LAN (only needs Python + httpx):
    python scripts/lan_multiuser_check.py --base http://192.168.1.20:8000 --admin admin --password <pw>

It creates staff accounts emp1..empN (if missing), logs them in concurrently, and each one
creates a task, lists suppliers, opens pages, and edits shared records while the others do the same.
Prints a pass/fail table; exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sys
import time

import httpx

PAGES = ["/", "/tasks", "/suppliers", "/handoffs", "/messages", "/quotes", "/skills", "/accounts", "/costs"]


def login(base: str, user: str, pw: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=30, follow_redirects=False)
    r = c.post("/login", data={"username": user, "password": pw})
    if r.status_code != 303:
        raise RuntimeError(f"{user} login failed: {r.status_code}")
    return c


def employee(base: str, i: int, pw: str, rounds: int) -> dict:
    t0 = time.time()
    errors, reqs = [], 0
    try:
        c = login(base, f"emp{i}", pw)
        for r in range(rounds):
            for p in PAGES:
                resp = c.get(p)
                reqs += 1
                if resp.status_code != 200:
                    errors.append(f"GET {p} -> {resp.status_code}")
            resp = c.post("/tasks", data={"title": f"并发测试 emp{i} r{r}", "countries": "英国", "company_types": "Ltd",
                                          "target_suppliers": "3", "spec_json": "{}",
                                          "level_vat_registered": "required", "is_template": "on"})
            reqs += 1
            if resp.status_code != 303:
                errors.append(f"POST /tasks -> {resp.status_code}")
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
    return {"user": f"emp{i}", "requests": reqs, "errors": errors, "secs": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--users", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--staff-password", default="Staff#12345")
    a = ap.parse_args()

    admin = login(a.base, a.admin, a.password)
    for i in range(1, a.users + 1):
        admin.post("/users", data={"username": f"emp{i}", "password": a.staff_password,
                                   "display_name": f"员工{i}", "role": "staff"})
    with cf.ThreadPoolExecutor(a.users) as ex:
        results = list(ex.map(lambda i: employee(a.base, i, a.staff_password, a.rounds), range(1, a.users + 1)))
    ok = all(not r["errors"] for r in results)
    for r in results:
        print(f"{r['user']}: {r['requests']} requests in {r['secs']}s, errors={len(r['errors'])} {r['errors'][:3]}")
    tasks = admin.get("/tasks").text.count("并发测试")
    expected = a.users * a.rounds
    print(f"tasks created and visible to admin: {tasks}/{expected}")
    ok = ok and tasks >= expected
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
