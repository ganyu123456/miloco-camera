"""报警信息 API"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.alert_service import alert_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    camera_id: Optional[int] = None,
    alert_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    return await alert_service.list_alerts(camera_id, alert_type, page, page_size)


@router.get("/stats")
async def alert_stats():
    return await alert_service.get_stats()


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int):
    ok = await alert_service.delete_alert(alert_id)
    if not ok:
        raise HTTPException(404, "Alert not found")
    return {"ok": True}


@router.get("/picture/{date}/{filename}")
async def get_picture(date: str, filename: str):
    """返回报警截图文件"""
    from app.config import settings
    path = settings.PICTURES_DIR / date / filename
    if not path.exists():
        raise HTTPException(404, "Picture not found")
    return FileResponse(str(path), media_type="image/jpeg")
