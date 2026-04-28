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
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "web" / "templates"
    return Path(__file__).parent.parent / "web" / "templates"


templates = Jinja2Templates(directory=str(_get_templates_dir()))

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="cameras.html")


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
    return templates.TemplateResponse(
        request=request, name="cameras.html", context={"cameras": cam_list}
    )


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
        }
        for s in states
    ]
    return templates.TemplateResponse(
        request=request,
        name="streams.html",
        context={
            "streams": stream_list,
            "mediamtx_running": rtsp_service.is_mediamtx_running(),
        },
    )
