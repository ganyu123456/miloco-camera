"""摄像头管理 API（零解码网关模式，无 MJPEG 预览）"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.camera import Camera
from app.services.camera_service import camera_manager
from app.services.rtsp_service import rtsp_service

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    name: str
    did: str
    brand: str = "xiaomi"     # xiaomi | rtsp
    model: Optional[str] = None
    local_ip: Optional[str] = None
    rtsp_url: Optional[str] = None
    channel: int = 0
    video_quality: str = "HIGH"
    enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    brand: Optional[str] = None
    channel: Optional[int] = None
    video_quality: Optional[str] = None
    local_ip: Optional[str] = None
    rtsp_url: Optional[str] = None


@router.get("")
async def list_cameras(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Camera))
    cameras = result.scalars().all()
    items = []
    for cam in cameras:
        d = cam.to_dict()
        state = camera_manager.get_state(cam.id)
        d["status"] = state.status if state else "stopped"
        d["error_msg"] = state.error_msg if state else ""
        d["rtsp_url"] = rtsp_service.get_rtsp_url(cam.id)
        items.append(d)
    return {"cameras": items}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_camera(body: CameraCreate, db: AsyncSession = Depends(get_db)):
    exists = (await db.execute(select(Camera).where(Camera.did == body.did))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"Camera did={body.did} already exists")

    cam = Camera(**body.model_dump())
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    if cam.enabled:
        camera_manager.register(
            cam.id, cam.name, cam.did,
            brand=cam.brand, channel=cam.channel,
            video_quality=cam.video_quality, rtsp_url=cam.rtsp_url,
        )
        asyncio.create_task(camera_manager.start(cam.id))
    return cam.to_dict()


@router.get("/{camera_id}")
async def get_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "Camera not found")
    d = cam.to_dict()
    state = camera_manager.get_state(cam.id)
    d["status"] = state.status if state else "stopped"
    d["rtsp_url"] = rtsp_service.get_rtsp_url(camera_id)
    return d


@router.patch("/{camera_id}")
async def update_camera(camera_id: int, body: CameraUpdate, db: AsyncSession = Depends(get_db)):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "Camera not found")

    update_data = body.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(cam, k, v)
    await db.commit()
    await db.refresh(cam)

    state = camera_manager.get_state(camera_id)
    if "enabled" in update_data:
        if cam.enabled and (state is None or state.status != "running"):
            camera_manager.register(
                cam.id, cam.name, cam.did,
                brand=cam.brand, channel=cam.channel,
                video_quality=cam.video_quality, rtsp_url=cam.rtsp_url,
            )
            asyncio.create_task(camera_manager.start(cam.id))
        elif not cam.enabled and state:
            asyncio.create_task(camera_manager.stop(cam.id))
    return cam.to_dict()


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "Camera not found")
    await camera_manager.stop(camera_id)
    camera_manager.unregister(camera_id)
    await db.delete(cam)
    await db.commit()


@router.post("/{camera_id}/start")
async def start_stream(camera_id: int, db: AsyncSession = Depends(get_db)):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "Camera not found")
    if not camera_manager.get_state(camera_id):
        camera_manager.register(
            cam.id, cam.name, cam.did,
            brand=cam.brand, channel=cam.channel,
            video_quality=cam.video_quality, rtsp_url=cam.rtsp_url,
        )
    ok = await camera_manager.start(camera_id)
    return {"ok": ok, "status": camera_manager.get_state(camera_id).status}


@router.post("/{camera_id}/stop")
async def stop_stream(camera_id: int):
    await camera_manager.stop(camera_id)
    return {"ok": True, "status": "stopped"}


@router.get("/discover/xiaomi")
async def discover_xiaomi_cameras():
    """调用小米 SDK 扫描在线摄像头设备"""
    try:
        from miloco_sdk import XiaomiClient
        from miloco_sdk.cli.utils import get_auth_info
        client = XiaomiClient()
        auth_info = get_auth_info(client)
        if not auth_info:
            raise HTTPException(401, "No auth_info found. Please login first.")
        client.set_access_token(auth_info["access_token"])
        device_list = client.home.get_device_list()
        online = [
            {
                "name": d.get("name"),
                "did": d.get("did"),
                "model": d.get("model"),
                "local_ip": d.get("localip"),
                "is_online": d.get("isOnline", False),
            }
            for d in device_list
        ]
        return {"devices": online}
    except Exception as e:
        raise HTTPException(500, str(e))
