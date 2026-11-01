"""Extract supplier identity and public contact details from page HTML/text."""

from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s().\-]{7,18}\d")
_BAD_EMAIL_PARTS = ("example.", "sentry", "wixpress", "@2x", ".png", ".jpg", ".gif", ".webp", ".svg", "domain.com",
                    "yourdomain", "email.com", "u003e", "@sentry", "noreply", "no-reply")


def registered_domain(url: str) -> str:
    try:
        import tldextract

        ext = tldextract.TLDExtract(suffix_list_urls=())(url)  # offline: use bundled suffix list
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    except Exception:
        pass
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def normalize_email(e: str) -> str:
    return e.strip().strip(".").lower()


def normalize_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    if p.strip().startswith("00"):
        digits = digits[2:]
    return "+" + digits


def _decode_cfemail(enc: str) -> str:
    try:
        key = int(enc[:2], 16)
        return "".join(chr(int(enc[i:i + 2], 16) ^ key) for i in range(2, len(enc), 2))
    except ValueError:
        return ""


def extract_contacts(html: str, text: str) -> list[dict]:
    out: dict[tuple, dict] = {}

    def add(ctype, value, norm):
        if norm and (ctype, norm) not in out:
            out[(ctype, norm)] = {"ctype": ctype, "value": value, "normalized": norm}

    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            e = unquote(href[7:].split("?")[0])
            if EMAIL_RE.fullmatch(e):
                add("email", e, normalize_email(e))
        elif low.startswith("tel:"):
            p = unquote(href[4:])
            if len(re.sub(r"\D", "", p)) >= 8:
                add("phone", p, normalize_phone(p))
        elif "wa.me/" in low or "api.whatsapp.com" in low:
            m = re.search(r"(?:wa\.me/|phone=)(\+?\d{8,15})", href)
            if m:
                add("whatsapp", m.group(1), normalize_phone(m.group(1)))
        elif "t.me/" in low:
            m = re.search(r"t\.me/([A-Za-z0-9_]{4,})", href)
            if m:
                add("telegram", "@" + m.group(1), m.group(1).lower())
        elif "linkedin.com/company" in low or "linkedin.com/in/" in low:
            add("linkedin", href, href.split("?")[0].rstrip("/").lower())
        elif "facebook.com/" in low and "sharer" not in low:
            add("facebook", href, href.split("?")[0].rstrip("/").lower())
    for el in soup.select("[data-cfemail]"):
        e = _decode_cfemail(el.get("data-cfemail", ""))
        if EMAIL_RE.fullmatch(e):
            add("email", e, normalize_email(e))
    for e in EMAIL_RE.findall(htmllib.unescape(text or "")):
        add("email", e, normalize_email(e))
    for p in PHONE_RE.findall(text or ""):
        if 9 <= len(re.sub(r"\D", "", p)) <= 15:
            add("phone", p.strip(), normalize_phone(p))
    if soup.find("form") and soup.find("textarea"):
        add("form", "网站联系表单", "form")
    return [c for c in out.values() if not (c["ctype"] == "email" and any(b in c["normalized"] for b in _BAD_EMAIL_PARTS))]


def company_name(html: str, title: str, domain: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") in ("Organization", "Corporation", "LocalBusiness",
                                                            "ProfessionalService") and it.get("name"):
                return str(it["name"])[:200]
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"):
        return og["content"].strip()[:200]
    if title:
        parts = [p.strip() for p in re.split(r"\s[|\-–—:]\s", title) if p.strip()]
        if parts:
            short = min(parts, key=len) if len(parts) > 1 else parts[0]
            return short[:200]
    return domain


def prefer_emails(contacts: list[dict], domain: str) -> list[str]:
    emails = [c["normalized"] for c in contacts if c["ctype"] == "email"]
    same = [e for e in emails if e.endswith("@" + domain) or e.endswith("." + domain)]
    rank = ("sales", "info", "enquir", "inquir", "contact", "hello", "office", "admin")

    def score(e):
        local = e.split("@")[0]
        return next((i for i, r in enumerate(rank) if r in local), len(rank))

    return sorted(same, key=score) + sorted([e for e in emails if e not in same], key=score)
