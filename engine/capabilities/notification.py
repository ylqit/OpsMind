"""
告警通知能力
支持多种通知渠道：邮件、钉钉、企业微信、Slack 等
"""
import smtplib
import httpx
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .base import BaseCapability, CapabilityMetadata
from .decorators import with_timeout, with_error_handling
from ..contracts import ActionResult


class EmailNotificationInput(BaseModel):
    """邮件通知输入"""
    to_emails: List[str] = Field(..., description="收件人邮箱列表")
    subject: str = Field(..., description="邮件主题", min_length=1, max_length=256)
    content: str = Field(..., description="邮件内容", min_length=1)
    smtp_host: str = Field(..., description="SMTP 服务器地址")
    smtp_port: int = Field(default=587, description="SMTP 端口", ge=1, le=65535)
    username: str = Field(..., description="SMTP 用户名")
    password: str = Field(..., description="SMTP 密码/授权码")
    from_email: str = Field(..., description="发件人邮箱")


class WebhookNotificationInput(BaseModel):
    """Webhook 通知输入"""
    webhook_url: str = Field(..., description="Webhook URL", min_length=1)
    title: str = Field(..., description="消息标题", min_length=1, max_length=256)
    content: str = Field(..., description="消息内容", min_length=1)
    mention_list: Optional[List[str]] = Field(default=None, description="需要@的用户列表")


class SendEmailNotification(BaseCapability):
    """
    邮件通知发送器
    支持发送 HTML 格式邮件
    """

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="send_email_notification",
            description="发送邮件通知（支持 HTML 格式）",
            version="1.0.0",
            tags=["notification", "email", "alert"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return EmailNotificationInput

    @with_timeout(timeout_seconds=30)
    @with_error_handling("SEND_EMAIL_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """发送邮件通知"""
        try:
            input_data = EmailNotificationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = input_data.subject
            msg['From'] = input_data.from_email
            msg['To'] = ', '.join(input_data.to_emails)

            html_content = f"<html><body><h3>{input_data.subject}</h3>{input_data.content.replace(chr(10), '<br>')}</body></html>"
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))

            server = smtplib.SMTP(input_data.smtp_host, input_data.smtp_port)
            server.starttls()
            server.login(input_data.username, input_data.password)
            server.sendmail(input_data.from_email, input_data.to_emails, msg.as_string())
            server.quit()

            return ActionResult.ok({"message": "邮件发送成功", "recipients": input_data.to_emails})
        except smtplib.SMTPException as e:
            return ActionResult.fail(f"SMTP 错误：{str(e)}", code="SMTP_ERROR")
        except Exception as e:
            return ActionResult.fail(f"发送失败：{str(e)}", code="SEND_ERROR")


class SendDingTalkNotification(BaseCapability):
    """钉钉机器人通知发送器"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="send_dingtalk_notification",
            description="发送钉钉机器人通知",
            version="1.0.0",
            tags=["notification", "dingtalk", "alert"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return WebhookNotificationInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("SEND_DINGTALK_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """发送钉钉通知"""
        try:
            input_data = WebhookNotificationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": input_data.title,
                "text": f"### {input_data.title}\n\n{input_data.content}"
            }
        }

        if input_data.mention_list:
            message["at"] = {"atMobiles": input_data.mention_list, "isAtAll": False}

        async with httpx.AsyncClient() as client:
            response = await client.post(input_data.webhook_url, json=message, headers={"Content-Type": "application/json"})
            result = response.json()

            if result.get("errcode") == 0:
                return ActionResult.ok({"message": "钉钉消息发送成功"})
            else:
                return ActionResult.fail(f"钉钉发送失败：{result.get('errmsg', '未知错误')}", code="DINGTALK_ERROR")


class SendWeComNotification(BaseCapability):
    """企业微信机器人通知发送器"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="send_wecom_notification",
            description="发送企业微信机器人通知",
            version="1.0.0",
            tags=["notification", "wecom", "alert"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return WebhookNotificationInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("SEND_WECOM_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """发送企业微信通知"""
        try:
            input_data = WebhookNotificationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        message = {
            "msgtype": "markdown",
            "markdown": {"content": f"### {input_data.title}\n\n{input_data.content}"}
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(input_data.webhook_url, json=message, headers={"Content-Type": "application/json"})
            result = response.json()

            if result.get("errcode") == 0:
                return ActionResult.ok({"message": "企业微信消息发送成功"})
            else:
                return ActionResult.fail(f"企业微信发送失败：{result.get('errmsg', '未知错误')}", code="WECOM_ERROR")


class SendSlackNotification(BaseCapability):
    """Slack 机器人通知发送器"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="send_slack_notification",
            description="发送 Slack 机器人通知",
            version="1.0.0",
            tags=["notification", "slack", "alert"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return WebhookNotificationInput

    @with_timeout(timeout_seconds=15)
    @with_error_handling("SEND_SLACK_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """发送 Slack 通知"""
        try:
            input_data = WebhookNotificationInput(**kwargs)
        except ValueError as e:
            return ActionResult.fail(str(e), code="INVALID_INPUT")

        is_alert = "告警" in input_data.title or "错误" in input_data.title
        message = {
            "attachments": [{
                "color": "#ff0000" if is_alert else "#36a64f",
                "title": input_data.title,
                "text": input_data.content,
                "ts": int(__import__('time').time())
            }]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(input_data.webhook_url, json=message, headers={"Content-Type": "application/json"})
            if response.status_code == 200:
                return ActionResult.ok({"message": "Slack 消息发送成功"})
            else:
                return ActionResult.fail(f"Slack 发送失败：{response.text}", code="SLACK_ERROR")


class AlertNotificationManager(BaseCapability):
    """告警通知管理器 - 统一管理和分发告警通知到多个渠道"""

    def _define_metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name="manage_alert_notification",
            description="管理告警通知（支持多渠道）",
            version="1.0.0",
            tags=["notification", "alert", "multi-channel"],
            requires_confirmation=False
        )

    def _define_input_schema(self) -> Type[BaseModel]:
        return BaseModel

    @with_timeout(timeout_seconds=30)
    @with_error_handling("ALERT_NOTIFICATION_ERROR")
    async def dispatch(self, **kwargs) -> ActionResult:
        """发送告警通知到多个渠道"""
        alert_title = kwargs.get("alert_title", "系统告警")
        alert_content = kwargs.get("alert_content", "")
        channels = kwargs.get("channels", ["dingtalk"])
        config = kwargs.get("config", {})

        results = {}

        for channel in channels:
            if channel == "dingtalk" and "dingtalk_webhook" in config:
                cap = SendDingTalkNotification()
                result = await cap.dispatch(webhook_url=config["dingtalk_webhook"], title=alert_title, content=alert_content)
                results["dingtalk"] = result.to_dict()

            elif channel == "wecom" and "wecom_webhook" in config:
                cap = SendWeComNotification()
                result = await cap.dispatch(webhook_url=config["wecom_webhook"], title=alert_title, content=alert_content)
                results["wecom"] = result.to_dict()

            elif channel == "slack" and "slack_webhook" in config:
                cap = SendSlackNotification()
                result = await cap.dispatch(webhook_url=config["slack_webhook"], title=alert_title, content=alert_content)
                results["slack"] = result.to_dict()

            elif channel == "email" and "smtp_config" in config:
                cap = SendEmailNotification()
                result = await cap.dispatch(
                    to_emails=config.get("email_recipients", []),
                    subject=alert_title,
                    content=alert_content,
                    smtp_host=config["smtp_config"]["host"],
                    smtp_port=config["smtp_config"].get("port", 587),
                    username=config["smtp_config"]["username"],
                    password=config["smtp_config"]["password"],
                    from_email=config["smtp_config"]["from_email"]
                )
                results["email"] = result.to_dict()

        return ActionResult.ok({"message": "通知发送完成", "results": results})
