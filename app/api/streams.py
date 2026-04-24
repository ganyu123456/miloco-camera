"""RTSP / 视频流路由"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.rtsp_service import rtsp_service
from app.services.camera_service import camera_manager

router = APIRouter(prefix="/api/streams", tags=["streams"])


@router.get("")
async def list_streams():
    """列出所有摄像头的 RTSP URL 和流状态"""
    states = camera_manager.all_states()
    items = []
    for s in states:
        items.append({
            "camera_id": s.camera_id,
            "name": s.name,
            "status": s.status,
            "rtsp_url": rtsp_service.get_rtsp_url(s.camera_id),
            "mjpeg_url": f"/api/cameras/{s.camera_id}/stream",
            "snapshot_url": f"/api/cameras/{s.camera_id}/snapshot",
            "rtsp_active": s.camera_id in rtsp_service._ffmpeg_procs,
        })
    return {"streams": items, "mediamtx_running": rtsp_service.is_mediamtx_running()}


@router.post("/{camera_id}/start-rtsp")
async def start_rtsp(camera_id: int, width: int = 1920, height: int = 1080, fps: int = 15):
    """为指定摄像头启动 RTSP 推流"""
    state = camera_manager.get_state(camera_id)
    if not state or state.status != "running":
        raise HTTPException(400, "Camera stream is not running")

    if not rtsp_service.is_mediamtx_running():
        rtsp_service.start_mediamtx()

    ok = rtsp_service.start_push(camera_id, width, height, fps)
    if ok:
        # 注册帧回调推流
        async def push_frame_cb(cid: int, jpeg_bytes: bytes) -> None:
            import cv2, numpy as np
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None:
                rtsp_service.push_frame(cid, frame.tobytes())

        state.add_frame_callback(push_frame_cb)

    return {
        "ok": ok,
        "rtsp_url": rtsp_service.get_rtsp_url(camera_id),
    }


@router.post("/{camera_id}/stop-rtsp")
async def stop_rtsp(camera_id: int):
    rtsp_service.stop_push(camera_id)
    return {"ok": True}


@router.get("/mediamtx/status")
async def mediamtx_status():
    return {
        "running": rtsp_service.is_mediamtx_running(),
        "rtsp_port": settings.RTSP_PORT,
    }


@router.post("/mediamtx/start")
async def start_mediamtx():
    ok = rtsp_service.start_mediamtx()
    return {"ok": ok, "running": rtsp_service.is_mediamtx_running()}


@router.post("/mediamtx/stop")
async def stop_mediamtx():
    rtsp_service.stop_mediamtx()
    return {"ok": True}
