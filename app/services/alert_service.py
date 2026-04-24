"""
报警服务：写入 SQLite、保存截图、触发通知
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class AlertService:

    async def create(
        self,
        camera_id: int,
        alert_type: str,
        label: str,
        confidence: float,
        snapshot_bytes: Optional[bytes] = None,
    ) -> dict:
        from app.database import AsyncSessionLocal
        from app.models.alert import Alert
        from app.models.camera import Camera
        from sqlalchemy import select

        snapshot_path: Optional[str] = None
        if snapshot_bytes:
            snapshot_path = self._save_snapshot(camera_id, alert_type, snapshot_bytes)

        async with AsyncSessionLocal() as db:
            # 获取摄像头名
            cam_result = await db.execute(select(Camera).where(Camera.id == camera_id))
            cam = cam_result.scalar_one_or_none()
            cam_name = cam.name if cam else f"camera_{camera_id}"

            alert = Alert(
                camera_id=camera_id,
                camera_name=cam_name,
                type=alert_type,
                label=label,
                confidence=confidence,
                snapshot_path=snapshot_path,
                notified=False,
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)
            alert_dict = alert.to_dict()

        logger.info(f"Alert created: [{alert_type}] {label} ({confidence:.2f}) camera={cam_name}")

        # 异步发送邮件通知（不阻塞主流程）
        if settings.SMTP_ENABLED:
            import asyncio
            from app.services.notify_service import notify_service
            asyncio.create_task(notify_service.send_alert(alert_dict, snapshot_bytes))

        return alert_dict

    def _save_snapshot(self, camera_id: int, alert_type: str, data: bytes) -> str:
        """保存报警截图到 data/pictures/YYYYMMDD/ 目录"""
        date_str = datetime.now().strftime("%Y%m%d")
        day_dir: Path = settings.PICTURES_DIR / date_str
        day_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%H%M%S_%f")[:12]
        filename = f"cam{camera_id}_{alert_type}_{ts}.jpg"
        filepath = day_dir / filename
        filepath.write_bytes(data)
        # 返回相对路径（供前端显示）
        return str(filepath.relative_to(settings.DATA_DIR.parent))

    async def list_alerts(
        self,
        camera_id: Optional[int] = None,
        alert_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        from app.database import AsyncSessionLocal
        from app.models.alert import Alert
        from sqlalchemy import select, func, desc

        offset = (page - 1) * page_size

        async with AsyncSessionLocal() as db:
            q = select(Alert)
            count_q = select(func.count()).select_from(Alert)
            if camera_id:
                q = q.where(Alert.camera_id == camera_id)
                count_q = count_q.where(Alert.camera_id == camera_id)
            if alert_type:
                q = q.where(Alert.type == alert_type)
                count_q = count_q.where(Alert.type == alert_type)

            total = (await db.execute(count_q)).scalar()
            q = q.order_by(desc(Alert.created_at)).offset(offset).limit(page_size)
            items = (await db.execute(q)).scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, -(-total // page_size)),
            "items": [a.to_dict() for a in items],
        }

    async def delete_alert(self, alert_id: int) -> bool:
        from app.database import AsyncSessionLocal
        from app.models.alert import Alert

        async with AsyncSessionLocal() as db:
            alert = await db.get(Alert, alert_id)
            if not alert:
                return False
            # 删除截图文件
            if alert.snapshot_path:
                p = Path(alert.snapshot_path)
                if p.exists():
                    p.unlink(missing_ok=True)
            await db.delete(alert)
            await db.commit()
        return True

    async def get_stats(self) -> dict:
        """报警统计（用于监控面板）"""
        from app.database import AsyncSessionLocal
        from app.models.alert import Alert
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as db:
            total = (await db.execute(select(func.count()).select_from(Alert))).scalar()
            unnotified = (await db.execute(
                select(func.count()).select_from(Alert).where(Alert.notified == False)
            )).scalar()
            type_counts_result = await db.execute(
                select(Alert.type, func.count(Alert.id)).group_by(Alert.type)
            )
            type_counts = {row[0]: row[1] for row in type_counts_result.all()}

        return {"total": total, "unnotified": unnotified, "by_type": type_counts}


alert_service = AlertService()
