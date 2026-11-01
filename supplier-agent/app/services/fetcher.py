"""Polite page fetching with robots.txt support and evidence snapshots on disk."""

from __future__ import annotations

import hashlib
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .. import config

MAX_BYTES = 3_000_000
_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_last_hit: dict[str, float] = {}


@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int = 0
    html: str = ""
    text: str = ""
    title: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.html) and not self.error


def _robots(url: str) -> urllib.robotparser.RobotFileParser | None:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base in _robots_cache:
        return _robots_cache[base]
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = httpx.get(base + "/robots.txt", timeout=10, follow_redirects=True,
                      headers={"User-Agent": config.HTTP_USER_AGENT})
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        else:
            rp = None  # no robots.txt => allowed
    except Exception:
        rp = None
    _robots_cache[base] = rp
    return rp


def allowed(url: str) -> bool:
    rp = _robots(url)
    return True if rp is None else rp.can_fetch(config.HTTP_USER_AGENT, url)


def html_to_text(html: str) -> str:
    try:
        import trafilatura

        main = trafilatura.extract(html, include_comments=False, include_tables=True, favor_recall=True) or ""
    except Exception:
        main = ""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    full = soup.get_text(" ", strip=True)
    # Footer/contact blocks are often dropped by trafilatura but carry emails/phones; keep both.
    return (main + "\n\n" + full) if main else full


def fetch(url: str, delay: float = 1.0) -> Page:
    page = Page(url=url)
    if not allowed(url):
        page.error = "robots.txt 禁止访问"
        return page
    host = urlparse(url).netloc
    wait = delay - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    try:
        with httpx.Client(follow_redirects=True, timeout=20, headers={
            "User-Agent": config.HTTP_USER_AGENT, "Accept-Language": "en,de;q=0.8,*;q=0.5"}) as c:
            r = c.get(url)
        page.status = r.status_code
        page.final_url = str(r.url)
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            page.error = f"非网页内容: {ctype}"
            return page
        page.html = r.text[:MAX_BYTES]
        if r.status_code != 200:
            page.error = f"HTTP {r.status_code}"
            return page
    except Exception as e:
        page.error = f"{type(e).__name__}: {e}"[:500]
        return page
    soup = BeautifulSoup(page.html, "html.parser")
    page.title = (soup.title.string or "").strip()[:500] if soup.title and soup.title.string else ""
    for a in soup.find_all("a", href=True):
        page.links.append((urljoin(page.final_url, a["href"]), a.get_text(" ", strip=True)[:120]))
    page.text = html_to_text(page.html)
    return page


def save_evidence(page: Page, supplier_id: int | None) -> dict:
    sha = hashlib.sha256(page.html.encode("utf-8", "ignore")).hexdigest() if page.html else ""
    folder = config.EVIDENCE_DIR / str(supplier_id or "unassigned")
    folder.mkdir(parents=True, exist_ok=True)
    html_path = text_path = ""
    if page.html:
        stem = f"{int(time.time())}_{sha[:12]}"
        (folder / f"{stem}.html").write_text(page.html, encoding="utf-8")
        (folder / f"{stem}.txt").write_text(f"URL: {page.final_url or page.url}\n\n{page.text}", encoding="utf-8")
        html_path = str((folder / f"{stem}.html").relative_to(config.DATA_DIR))
        text_path = str((folder / f"{stem}.txt").relative_to(config.DATA_DIR))
    return {"sha256": sha, "html_path": html_path, "text_path": text_path}


SUBPAGE_HINTS = ["contact", "kontakt", "contatt", "contacto", "about", "shelf", "ready", "readymade", "aged",
                 "vorrat", "price", "pricing", "preise", "prezzi", "precios", "vat", "bank", "director", "list",
                 "companies-for-sale", "company-for-sale", "impressum", "nominee"]


def pick_subpages(page: Page, limit: int) -> list[str]:
    host = urlparse(page.final_url or page.url).netloc.lower().removeprefix("www.")
    scored = []
    seen = set()
    for href, label in page.links:
        p = urlparse(href)
        if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
            continue
        clean = href.split("#")[0]
        if clean in seen or clean.rstrip("/") == (page.final_url or page.url).rstrip("/"):
            continue
        seen.add(clean)
        hay = (p.path + " " + label).lower()
        score = sum(2 if h in p.path.lower() else 1 for h in SUBPAGE_HINTS if h in hay)
        if score and not any(clean.lower().endswith(x) for x in (".pdf", ".jpg", ".png", ".zip", ".doc", ".docx")):
            scored.append((score, clean))
    scored.sort(key=lambda x: -x[0])
    return [u for _, u in scored[:limit]]
