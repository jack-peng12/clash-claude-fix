from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="staff")  # admin/manager/staff/viewer
    email: Mapped[str] = mapped_column(String(256), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcurementTask(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # draft/queued/running/paused/cancelled/completed/failed
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_outreach: Mapped[bool] = mapped_column(Boolean, default=False)
    continuous: Mapped[bool] = mapped_column(Boolean, default=False)
    rounds_done: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SearchRun(Base):
    __tablename__ = "search_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    query: Mapped[str] = mapped_column(String(512))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    origin: Mapped[str] = mapped_column(String(32), default="template")  # template/adaptive/llm
    engine: Mapped[str] = mapped_column(String(32), default="ddgs")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    relevant_count: Mapped[int] = mapped_column(Integer, default=0)
    new_suppliers: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    domain: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)
    website: Mapped[str] = mapped_column(String(512), default="")
    country_hint: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    source_channel: Mapped[str] = mapped_column(String(32), default="web")
    status: Mapped[str] = mapped_column(String(24), default="new")
    # new/screened/contacted/replied/human_takeover/rejected/opted_out/closed
    fit_category: Mapped[str] = mapped_column(String(24), default="unscreened")
    # match/no_match/insufficient/high_risk/unscreened
    fit_score: Mapped[float] = mapped_column(Float, default=0)
    risk_level: Mapped[str] = mapped_column(String(16), default="unknown")  # low/medium/high/unknown
    intent_score: Mapped[float] = mapped_column(Float, default=0)
    intent_level: Mapped[str] = mapped_column(String(16), default="none")  # none/low/medium/high
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_over: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_over_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    followup_count: Mapped[int] = mapped_column(Integer, default=0)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    contacts = relationship("Contact", back_populates="supplier", cascade="all, delete-orphan")
    facts = relationship("Fact", back_populates="supplier", cascade="all, delete-orphan")


class SupplierTask(Base):
    __tablename__ = "supplier_tasks"
    __table_args__ = (UniqueConstraint("supplier_id", "task_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    found_by_query: Mapped[str] = mapped_column(String(512), default="")
    fit_category: Mapped[str] = mapped_column(String(24), default="unscreened")
    fit_score: Mapped[float] = mapped_column(Float, default=0)
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("ctype", "normalized"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    ctype: Mapped[str] = mapped_column(String(24))  # email/phone/whatsapp/telegram/linkedin/facebook/form
    value: Mapped[str] = mapped_column(String(512))
    normalized: Mapped[str] = mapped_column(String(512))
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    bounced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    supplier = relationship("Supplier", back_populates="contacts")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    url: Mapped[str] = mapped_column(String(1024))
    final_url: Mapped[str] = mapped_column(String(1024), default="")
    http_status: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    html_path: Mapped[str] = mapped_column(String(512), default="")
    text_path: Mapped[str] = mapped_column(String(512), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Fact(Base):
    """A single claim about a supplier and how well it is evidenced.

    status: web_claim (seen on the supplier's website), supplier_claim (said in a message),
    doc_provided (supplier sent a document, not yet checked), human_verified, unknown.
    AI may never set human_verified.
    """

    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text, default="")
    polarity: Mapped[str] = mapped_column(String(8), default="yes")  # yes/no/unknown
    status: Mapped[str] = mapped_column(String(24), default="web_claim")
    snippet: Mapped[str] = mapped_column(Text, default="")
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    supplier = relationship("Supplier", back_populates="facts")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(24), default="email")
    direction: Mapped[str] = mapped_column(String(4))  # out/in
    kind: Mapped[str] = mapped_column(String(16), default="initial")  # initial/followup/clarify/manual/inbound
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    body_zh: Mapped[str] = mapped_column(Text, default="")
    to_addr: Mapped[str] = mapped_column(String(512), default="")
    actual_to_addr: Mapped[str] = mapped_column(String(512), default="")
    from_addr: Mapped[str] = mapped_column(String(512), default="")
    header_message_id: Mapped[str] = mapped_column(String(512), default="")
    in_reply_to: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # draft/approved/queued/sent/failed/blocked/received
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    dedupe_key: Mapped[str] = mapped_column(String(256), default="")
    created_by: Mapped[str] = mapped_column(String(32), default="ai")
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SupplierQuestion(Base):
    __tablename__ = "supplier_questions"
    __table_args__ = (UniqueConstraint("supplier_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    key: Mapped[str] = mapped_column(String(64))
    asked_count: Mapped[int] = mapped_column(Integer, default=0)
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    answer_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)


class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0)
    triggered: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(16), default="ai")  # ai/manual
    status: Mapped[str] = mapped_column(String(16), default="open")  # open/accepted/closed
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(256), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    active_version: Mapped[int] = mapped_column(Integer, default=1)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    test_result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    config_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    # unverified/active/expired/error/disabled
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ManualAction(Base):
    """Work the AI prepared but a human must perform (platforms without an allowed API)."""

    __tablename__ = "manual_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    target: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    jtype: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued/running/done/failed/cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CostRecord(Base):
    __tablename__ = "cost_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64), default="")
    purpose: Mapped[str] = mapped_column(String(64), default="")
    units_in: Mapped[int] = mapped_column(Integer, default=0)
    units_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(8), default="INFO")
    source: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
