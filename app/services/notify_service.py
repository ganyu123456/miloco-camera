"""QQ 邮件异步推送服务"""
import asyncio
import logging
import smtplib
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class NotifyService:

    async def send_alert(self, alert: dict, snapshot_bytes: Optional[bytes] = None) -> bool:
        """异步发送报警邮件（在线程池中执行，避免阻塞事件循环）"""
        if not settings.SMTP_ENABLED or not settings.SMTP_USER or not settings.SMTP_TO:
            return False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_sync, alert, snapshot_bytes)
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    def _send_sync(self, alert: dict, snapshot_bytes: Optional[bytes]) -> None:
        """同步邮件发送（smtplib）"""
        alert_type = alert.get("type", "未知")
        camera_name = alert.get("camera_name", "未知摄像头")
        label = alert.get("label", "")
        confidence = alert.get("confidence", 0)
        created_at = alert.get("created_at", "")

        subject = f"[AI网关报警] {camera_name} - {alert_type} 检测到 {label}"

        body = f"""
        <html><body>
        <h2 style="color:#e74c3c;">⚠️ AI 视频网关报警通知</h2>
        <table border="1" cellpadding="8" style="border-collapse:collapse;">
          <tr><td><b>摄像头</b></td><td>{camera_name}</td></tr>
          <tr><td><b>报警类型</b></td><td>{alert_type}</td></tr>
          <tr><td><b>检测目标</b></td><td>{label}</td></tr>
          <tr><td><b>置信度</b></td><td>{confidence:.1%}</td></tr>
          <tr><td><b>报警时间</b></td><td>{created_at}</td></tr>
        </table>
        <p>请及时查看监控系统。</p>
        </body></html>
        """

        msg = MIMEMultipart("mixed")
        msg["From"] = settings.SMTP_USER
        msg["To"] = settings.SMTP_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html", "utf-8"))

        if snapshot_bytes:
            part = MIMEBase("image", "jpeg")
            part.set_payload(snapshot_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename="snapshot.jpg")
            msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, settings.SMTP_TO.split(","), msg.as_string())

        logger.info(f"Alert email sent to {settings.SMTP_TO}")


notify_service = NotifyService()
