"""摄像头管理 API"""
import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.camera import Camera
from app.services.camera_service import camera_manager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    name: str
    did: str
    model: Optional[str] = None
    local_ip: Optional[str] = None
    channel: int = 0
    video_quality: str = "HIGH"
    enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    channel: Optional[int] = None
    video_quality: Optional[str] = None
    local_ip: Optional[str] = None


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
        items.append(d)
    return {"cameras": items}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_camera(body: CameraCreate, db: AsyncSession = Depends(get_db)):
    # 检查 did 唯一性
    exists = (await db.execute(select(Camera).where(Camera.did == body.did))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, f"Camera did={body.did} already exists")

    cam = Camera(**body.model_dump())
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    # 如果 enabled，立即注册并启动流
    if cam.enabled:
        camera_manager.register(cam.id, cam.name, cam.did, cam.channel, cam.video_quality)
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

    # 同步运行时状态
    state = camera_manager.get_state(camera_id)
    if "enabled" in update_data:
        if cam.enabled and (state is None or state.status != "running"):
            camera_manager.register(cam.id, cam.name, cam.did, cam.channel, cam.video_quality)
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
        camera_manager.register(cam.id, cam.name, cam.did, cam.channel, cam.video_quality)
    ok = await camera_manager.start(camera_id)
    return {"ok": ok, "status": camera_manager.get_state(camera_id).status}


@router.post("/{camera_id}/stop")
async def stop_stream(camera_id: int):
    await camera_manager.stop(camera_id)
    return {"ok": True, "status": "stopped"}


@router.get("/{camera_id}/snapshot")
async def get_snapshot(camera_id: int):
    """返回最新一帧 JPEG 截图"""
    from fastapi.responses import Response
    state = camera_manager.get_state(camera_id)
    if not state or not state.latest_frame:
        raise HTTPException(404, "No frame available")
    return Response(content=state.latest_frame, media_type="image/jpeg")


@router.get("/{camera_id}/stream")
async def mjpeg_stream(camera_id: int):
    """MJPEG 视频流（浏览器直接播放）"""
    import asyncio
    from fastapi.responses import StreamingResponse

    async def frame_generator():
        state = camera_manager.get_state(camera_id)
        if not state:
            return
        while True:
            try:
                await asyncio.wait_for(state.frame_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            if state.latest_frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + state.latest_frame + b"\r\n"
                )

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


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
