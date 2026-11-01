from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    from_addr: str
    to_addr: str
    subject: str
    body: str
    header_message_id: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    is_bounce: bool = False


class AuthExpired(Exception):
    """Credentials/session no longer valid; the account must be re-authorised by a human."""


class Connector:
    platform = "base"
    label = "基础"
    # What the platform officially allows this connector to do automatically.
    capabilities: dict[str, str] = {}
    config_fields: list[tuple[str, str, str]] = []  # (name, label, input type)
    implemented = False
    note = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def verify(self) -> str:
        raise NotImplementedError

    def send(self, to: str, subject: str, body: str, message_id: str, in_reply_to: str = "",
             references: str = "") -> None:
        raise NotImplementedError

    def fetch_new(self, state: dict) -> tuple[list[InboundMessage], dict]:
        return [], state
