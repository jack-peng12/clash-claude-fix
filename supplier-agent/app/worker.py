"""Background worker: DB-backed job queue + periodic scheduler.

Runs as a thread inside the web process (default) or standalone: `python -m app.worker`.
Jobs survive restarts because they live in the database; a job left in `running` by a crash is
re-queued on startup.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import timedelta

from . import config
from .db import init_db, session_scope
from .models import Job, ProcurementTask, utcnow
from .services import settings
from .services.logs import syslog

log = logging.getLogger("supplier_agent.worker")
_stop = threading.Event()
_last_periodic: dict[str, float] = {}


def handle(job: Job) -> str:
    p = job.payload or {}
    if job.jtype == "task_round":
        from .services.pipeline import run_round

        run_round(int(p["task_id"]))
        return "ok"
    if job.jtype == "send_message":
        from .services.messaging import deliver

        with session_scope() as db:
            return deliver(db, int(p["message_id"]))
    if job.jtype == "poll_inbox":
        from .services.inbox import poll_all

        with session_scope() as db:
            return str(poll_all(db))
    if job.jtype == "followups":
        from .services.followup import run

        with session_scope() as db:
            return str(run(db))
    if job.jtype == "backup":
        from .services.backup import create_backup

        return create_backup()
    raise ValueError(f"unknown job type {job.jtype}")


LONG_JOBS = ("task_round",)


def _claim(long_jobs: bool | None = None) -> Job | None:
    with session_scope() as db:
        q = db.query(Job).filter(Job.status == "queued", Job.run_after <= utcnow())
        if long_jobs is True:
            q = q.filter(Job.jtype.in_(LONG_JOBS))
        elif long_jobs is False:
            q = q.filter(Job.jtype.notin_(LONG_JOBS))
        job = q.order_by(Job.run_after.asc(), Job.id.asc()).first()
        if job is None:
            return None
        if job.jtype == "task_round":
            t = db.get(ProcurementTask, int(job.payload.get("task_id", 0)))
            if t is None or t.status in ("paused", "cancelled", "completed"):
                job.status, job.finished_at = "cancelled", utcnow()
                return None
        job.status, job.attempts = "running", job.attempts + 1
        db.flush()
        db.expunge(job)
        return job


def run_once(long_jobs: bool | None = None) -> bool:
    job = _claim(long_jobs)
    if job is None:
        return False
    try:
        result = handle(job)
        with session_scope() as db:
            j = db.get(Job, job.id)
            j.status, j.finished_at, j.last_error = "done", utcnow(), str(result)[:2000] if result else ""
    except Exception as e:
        tb = traceback.format_exc()
        syslog("ERROR", f"job:{job.jtype}", f"job {job.id} 失败: {e}\n{tb[-1500:]}")
        with session_scope() as db:
            j = db.get(Job, job.id)
            j.last_error = f"{type(e).__name__}: {e}"[:2000]
            if j.attempts < j.max_attempts:
                j.status, j.run_after = "queued", utcnow() + timedelta(minutes=2 ** j.attempts)
            else:
                j.status, j.finished_at = "failed", utcnow()
                if job.jtype == "task_round":
                    t = db.get(ProcurementTask, int(job.payload.get("task_id", 0)))
                    if t:
                        t.status, t.last_error = "failed", j.last_error
    return True


def _enqueue_unique(db, jtype: str) -> None:
    if not db.query(Job).filter(Job.jtype == jtype, Job.status.in_(["queued", "running"])).first():
        db.add(Job(jtype=jtype, payload={}, max_attempts=1))


def periodic() -> None:
    now = time.time()
    with session_scope() as db:
        st = settings.all_settings(db)
        plan = {"poll_inbox": float(st["inbox_poll_minutes"]) * 60,
                "followups": float(st["followup_check_minutes"]) * 60,
                "backup": 24 * 3600}
        for jtype, every in plan.items():
            if every <= 0:
                continue
            if now - _last_periodic.get(jtype, 0) >= every:
                _last_periodic[jtype] = now
                if jtype == "backup" and _last_periodic.get("_boot") is None:
                    _last_periodic["_boot"] = now
                    continue
                _enqueue_unique(db, jtype)


def recover() -> None:
    with session_scope() as db:
        n = db.query(Job).filter(Job.status == "running").update({"status": "queued"})
        if n:
            syslog("WARNING", "worker", f"恢复 {n} 个中断的任务")


def loop(long_jobs: bool | None = None, with_periodic: bool = True) -> None:
    while not _stop.is_set():
        try:
            if with_periodic:
                periodic()
            busy = run_once(long_jobs)
        except Exception as e:
            syslog("ERROR", "worker", f"worker loop error: {e}")
            busy = False
        if not busy:
            _stop.wait(config.WORKER_POLL_SECONDS)


def start_threads() -> list[threading.Thread]:
    """One thread for long search/collect rounds, one for messaging/inbox/follow-ups."""
    recover()
    syslog("INFO", "worker", "后台 Worker 已启动")
    threads = [threading.Thread(target=loop, args=(True, False), name="sa-worker-tasks", daemon=True),
               threading.Thread(target=loop, args=(False, True), name="sa-worker-msg", daemon=True)]
    for t in threads:
        t.start()
    return threads


def stop() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    for t in start_threads():
        t.join()
