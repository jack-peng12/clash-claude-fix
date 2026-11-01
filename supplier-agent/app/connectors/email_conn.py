from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from .base import AuthExpired, Connector, InboundMessage


def _dh(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


def _body(msg: email.message.Message) -> tuple[str, list[str]]:
    text, html, atts = "", "", []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        disp = (part.get("Content-Disposition") or "").lower()
        fname = part.get_filename()
        if fname or "attachment" in disp:
            atts.append(_dh(fname) or "attachment")
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            s = payload.decode(charset, "replace")
        except LookupError:
            s = payload.decode("utf-8", "replace")
        if part.get_content_type() == "text/plain" and not text:
            text = s
        elif part.get_content_type() == "text/html" and not html:
            html = s
    if not text and html:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return text, atts


class EmailConnector(Connector):
    platform = "email"
    label = "电子邮箱 (SMTP/IMAP)"
    implemented = True
    capabilities = {"send": "auto", "receive": "auto", "search": "none", "post": "none"}
    config_fields = [
        ("from_addr", "发件地址", "text"), ("from_name", "发件人名称", "text"),
        ("smtp_host", "SMTP 服务器", "text"), ("smtp_port", "SMTP 端口", "number"),
        ("smtp_security", "SMTP 加密 (ssl/starttls/none)", "text"),
        ("imap_host", "IMAP 服务器", "text"), ("imap_port", "IMAP 端口", "number"),
        ("imap_security", "IMAP 加密 (ssl/none)", "text"), ("imap_folder", "收件箱文件夹", "text"),
        ("username", "登录用户名", "text"), ("password", "密码/应用专用密码/授权码", "password"),
    ]
    note = "使用邮箱服务商的应用专用密码或授权码；密码加密保存，不以明文存储。"

    def _smtp(self) -> smtplib.SMTP:
        c = self.cfg
        host, port, sec = c["smtp_host"], int(c.get("smtp_port") or 587), (c.get("smtp_security") or "starttls").lower()
        if sec == "ssl":
            s = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(host, port, timeout=30)
            if sec == "starttls":
                s.starttls(context=ssl.create_default_context())
        if c.get("username"):
            try:
                s.login(c["username"], c.get("password", ""))
            except smtplib.SMTPAuthenticationError as e:
                raise AuthExpired(f"SMTP 登录失败: {e}") from e
        return s

    def _imap(self) -> imaplib.IMAP4:
        c = self.cfg
        host, port = c["imap_host"], int(c.get("imap_port") or 993)
        m = imaplib.IMAP4_SSL(host, port) if (c.get("imap_security") or "ssl").lower() == "ssl" else imaplib.IMAP4(host, port)
        try:
            m.login(c.get("username", ""), c.get("password", ""))
        except imaplib.IMAP4.error as e:
            raise AuthExpired(f"IMAP 登录失败: {e}") from e
        return m

    def verify(self) -> str:
        s = self._smtp()
        s.quit()
        if self.cfg.get("imap_host"):
            m = self._imap()
            m.select(self.cfg.get("imap_folder") or "INBOX", readonly=True)
            m.logout()
        return "SMTP/IMAP 连接与登录成功"

    def send(self, to: str, subject: str, body: str, message_id: str, in_reply_to: str = "",
             references: str = "") -> None:
        msg = EmailMessage()
        msg["From"] = formataddr((self.cfg.get("from_name") or "", self.cfg["from_addr"]))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = (references + " " + in_reply_to).strip()
        msg.set_content(body)
        s = self._smtp()
        try:
            s.send_message(msg)
        finally:
            try:
                s.quit()
            except Exception:
                pass

    def fetch_new(self, state: dict) -> tuple[list[InboundMessage], dict]:
        m = self._imap()
        out: list[InboundMessage] = []
        try:
            m.select(self.cfg.get("imap_folder") or "INBOX")
            last = int(state.get("last_uid", 0))
            typ, data = m.uid("search", None, f"UID {last + 1}:*")
            uids = [int(u) for u in (data[0] or b"").split() if int(u) > last]
            for uid in uids[:200]:
                typ, msgdata = m.uid("fetch", str(uid), "(RFC822)")
                if typ != "OK" or not msgdata or not isinstance(msgdata[0], tuple):
                    continue
                raw = email.message_from_bytes(msgdata[0][1])
                text, atts = _body(raw)
                frm = parseaddr(_dh(raw.get("From")))[1].lower()
                subj = _dh(raw.get("Subject"))
                bounce = frm.startswith(("mailer-daemon", "postmaster")) or "delivery status notification" in subj.lower() \
                    or "undeliverable" in subj.lower() or raw.get_content_type() == "multipart/report"
                out.append(InboundMessage(
                    from_addr=frm, to_addr=parseaddr(_dh(raw.get("To")))[1].lower(), subject=subj, body=text,
                    header_message_id=(raw.get("Message-ID") or "").strip(),
                    in_reply_to=(raw.get("In-Reply-To") or "").strip(),
                    references=(raw.get("References") or "").split(), attachments=atts, is_bounce=bounce))
                state["last_uid"] = uid
        finally:
            try:
                m.logout()
            except Exception:
                pass
        return out, state
