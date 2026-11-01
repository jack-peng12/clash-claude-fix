from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..models import Notification, User

ROLE_RANK = {"viewer": 0, "staff": 1, "manager": 2, "admin": 3}
ROLE_LABEL = {"viewer": "只读", "staff": "业务员", "manager": "主管", "admin": "管理员"}

templates = Jinja2Templates(directory=str(config.BASE_DIR / "web" / "templates"))
TZ = ZoneInfo("Asia/Shanghai")


def _dt(v, fmt="%Y-%m-%d %H:%M"):
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc).astimezone(TZ).strftime(fmt)
    return str(v)


def _pretty(v):
    return json.dumps(v, ensure_ascii=False, indent=2)


LABELS = {
    "task_status": {"draft": "草稿", "queued": "排队中", "running": "运行中", "paused": "已暂停",
                    "cancelled": "已取消", "completed": "已完成", "failed": "失败"},
    "supplier_status": {"new": "新建", "screened": "已筛选", "contacted": "已联系", "replied": "已回复",
                        "human_takeover": "人工接管", "rejected": "已排除", "opted_out": "拒绝联系", "closed": "已关闭"},
    "fit": {"match": "符合", "no_match": "不符合", "insufficient": "资料不足", "high_risk": "风险较高",
            "unscreened": "未筛选"},
    "intent": {"none": "无", "low": "低", "medium": "中", "high": "高"},
    "risk": {"low": "低", "medium": "中", "high": "高", "unknown": "未知"},
    "msg_status": {"draft": "草稿待审", "approved": "已批准", "queued": "待发送", "sent": "已发送",
                   "failed": "失败", "blocked": "已拦截", "received": "已接收"},
    "fact_status": {"web_claim": "网站声称", "supplier_claim": "供应商声称", "doc_provided": "已提供文件(未核验)",
                    "human_verified": "人工已核验", "unknown": "未知"},
    "level": {"required": "必须满足", "preferred": "优先满足", "not_required": "不作要求", "to_confirm": "待确认"},
    "polarity": {"yes": "是", "no": "否", "unknown": "未知"},
    "acc_status": {"unverified": "未验证", "active": "正常", "expired": "授权失效", "error": "错误", "disabled": "停用"},
    "kind": {"initial": "首封开发信", "followup": "跟进", "clarify": "追问", "manual": "人工", "inbound": "来信",
             "suggestion": "AI拟稿"},
}


def _label(v, group):
    return LABELS.get(group, {}).get(v, v)


templates.env.filters["dt"] = _dt
templates.env.filters["pretty"] = _pretty
templates.env.filters["label"] = _label
templates.env.globals["ROLE_LABEL"] = ROLE_LABEL
templates.env.globals["LABELS"] = LABELS


class LoginRequired(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or not user.active:
        raise LoginRequired()
    return user


def require(min_role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[min_role]:
            raise HTTPException(403, "权限不足")
        return user

    return dep


def render(request: Request, db: Session, user: User | None, name: str, **ctx):
    unread = db.query(Notification).filter_by(read=False).count() if user else 0
    return templates.TemplateResponse(request, name, {"user": user, "unread": unread,
                                                      "can": lambda r: user and ROLE_RANK[user.role] >= ROLE_RANK[r],
                                                      **ctx})
