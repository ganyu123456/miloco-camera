"""HTML 页面路由（Jinja2 模板）"""
import sys
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db


def _get_templates_dir() -> Path:
    """
    PyInstaller --onefile 时模板在 sys._MEIPASS/web/templates；
    普通运行时在 app/web/templates（相对于本文件上两级）。
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "web" / "templates"
    return Path(__file__).parent.parent / "web" / "templates"


templates = Jinja2Templates(directory=str(_get_templates_dir()))

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("cameras.html", {"request": request})


@router.get("/cameras", response_class=HTMLResponse)
async def cameras_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.models.camera import Camera
    from app.services.camera_service import camera_manager
    result = await db.execute(select(Camera))
    cameras = result.scalars().all()
    cam_list = []
    for cam in cameras:
        d = cam.to_dict()
        state = camera_manager.get_state(cam.id)
        d["status"] = state.status if state else "stopped"
        cam_list.append(d)
    return templates.TemplateResponse("cameras.html", {"request": request, "cameras": cam_list})


@router.get("/detections", response_class=HTMLResponse)
async def detections_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.models.camera import Camera
    from app.models.detection import DetectionConfig
    cameras = (await db.execute(select(Camera))).scalars().all()
    detections = (await db.execute(select(DetectionConfig))).scalars().all()
    return templates.TemplateResponse("detections.html", {
        "request": request,
        "cameras": [c.to_dict() for c in cameras],
        "detections": [d.to_dict() for d in detections],
    })


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, db: AsyncSession = Depends(get_db)):
    from app.models.camera import Camera
    cameras = (await db.execute(select(Camera))).scalars().all()
    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "cameras": [c.to_dict() for c in cameras],
    })


@router.get("/streams", response_class=HTMLResponse)
async def streams_page(request: Request):
    from app.services.camera_service import camera_manager
    from app.services.rtsp_service import rtsp_service
    states = camera_manager.all_states()
    stream_list = [
        {
            "camera_id": s.camera_id,
            "name": s.name,
            "status": s.status,
            "rtsp_url": rtsp_service.get_rtsp_url(s.camera_id),
            "mjpeg_url": f"/api/cameras/{s.camera_id}/stream",
        }
        for s in states
    ]
    return templates.TemplateResponse("streams.html", {
        "request": request,
        "streams": stream_list,
        "mediamtx_running": rtsp_service.is_mediamtx_running(),
    })


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    return templates.TemplateResponse("monitor.html", {"request": request})
