"""Social / messaging platform connectors.

None of these platforms officially allow automated cold direct messages to strangers. Where an
official API exists for a subset of actions it is listed in `capabilities`; everything else runs in
"manual" mode: the AI prepares the content and target, a human performs and confirms the action.
"""

from __future__ import annotations

import httpx

from .base import AuthExpired, Connector


class ManualConnector(Connector):
    implemented = True
    capabilities = {"search": "manual", "post": "manual", "dm": "manual", "reply": "manual"}
    config_fields = [("profile_url", "账号主页链接（仅用于记录，不保存密码）", "text")]

    def verify(self) -> str:
        return "人工确认模式：系统不保存该平台密码，AI 只生成内容和待办，由员工在平台上执行并回填结果。"


class FacebookConnector(ManualConnector):
    platform, label = "facebook", "Facebook"
    note = "Graph API 仅允许管理自己主页的帖子；不允许自动加入群组或陌生私信 → 人工确认模式。"


class LinkedInConnector(ManualConnector):
    platform, label = "linkedin", "LinkedIn"
    note = "LinkedIn 官方 API 不开放搜索他人和自动私信；自动化浏览违反用户协议 → 人工确认模式。"


class WhatsAppConnector(ManualConnector):
    platform, label = "whatsapp", "WhatsApp"
    note = ("WhatsApp Business Cloud API 只能向已同意的用户发送预审模板消息；陌生开发须人工发起。"
            "如申请了 Business API，可后续扩展为模板消息自动发送。")


class DiscordConnector(ManualConnector):
    platform, label = "discord", "Discord"
    note = "Bot 只能在被邀请的服务器内工作，禁止自动化用户账号（self-bot）→ 人工确认模式。"


class RedditConnector(ManualConnector):
    platform, label = "reddit", "Reddit"
    note = "Reddit 官方 API 需注册应用（OAuth）；发帖需遵守各社区规则。当前为人工确认模式，API 搜索待接入。"


class TelegramBotConnector(Connector):
    platform, label = "telegram", "Telegram (Bot API)"
    implemented = True
    capabilities = {"search": "none", "post": "auto_in_own_channels", "dm": "only_users_who_started_bot",
                    "reply": "auto_in_groups_bot_joined"}
    config_fields = [("bot_token", "Bot Token（@BotFather 获取）", "password")]
    note = "官方 Bot API：只能给主动联系过机器人的用户发消息、在已加入的群组中发言；不能主动私信陌生人。"

    def verify(self) -> str:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{self.cfg.get('bot_token', '')}/getMe", timeout=15)
        except httpx.HTTPError as e:
            raise RuntimeError(f"网络错误: {e}") from e
        if r.status_code == 401:
            raise AuthExpired("Bot Token 无效或已被撤销")
        r.raise_for_status()
        return f"已连接机器人 @{r.json()['result'].get('username')}"
