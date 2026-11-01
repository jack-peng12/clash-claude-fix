from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, config
from .db import init_db, session_scope
from .models import User
from .security import hash_password, session_secret
from .skills import engine as skills

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
for _noisy in ("httpx", "primp", "ddgs", "ddgs.ddgs", "trafilatura"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def bootstrap() -> None:
    init_db()
    with session_scope() as db:
        skills.seed(db)
        if db.query(User).count() == 0:
            db.add(User(username=config.ADMIN_USERNAME, display_name="管理员", role="admin",
                        password_hash=hash_password(config.ADMIN_PASSWORD)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    if config.RUN_WORKER:
        from .worker import start_threads, stop

        start_threads()
    yield
    if config.RUN_WORKER:
        stop()


def create_app() -> FastAPI:
    app = FastAPI(title="全球现成公司供应商开发Agent", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site="strict",
                       session_cookie="sa_session", max_age=7 * 24 * 3600)
    app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "web" / "static")), name="static")
    from fastapi.responses import RedirectResponse

    from .web.deps import LoginRequired
    from .web.routes import router

    @app.exception_handler(LoginRequired)
    async def _login_redirect(request, exc):
        return RedirectResponse("/login", status_code=303)

    app.include_router(router)
    return app


app = create_app()
