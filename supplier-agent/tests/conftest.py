import os
import socket
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="sa_test_")
os.environ["SA_DATA_DIR"] = _tmp
os.environ["SA_RUN_WORKER"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.db import Base, engine, session_scope  # noqa: E402
from app.main import bootstrap  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fresh_db():
    Base.metadata.drop_all(engine)
    bootstrap()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(fresh_db):
    with session_scope() as s:
        yield s


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve(directory: Path, host: str):
    srv = ThreadingHTTPServer((host, 0), partial(_Quiet, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(scope="session")
def fixture_sites():
    """Two local supplier websites on different hostnames so they dedupe as different suppliers."""
    a = _serve(FIXTURES / "site_acme", "127.0.0.1")
    b = _serve(FIXTURES / "site_risky", "127.0.0.1")
    yield {"acme": f"http://127.0.0.1:{a.server_port}/", "risky": f"http://localhost:{b.server_port}/"}
    a.shutdown()
    b.shutdown()


def greenmail_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 3025), timeout=1), \
                socket.create_connection(("127.0.0.1", 3143), timeout=1):
            return True
    except OSError:
        return False
