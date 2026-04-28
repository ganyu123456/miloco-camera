"""RTSP / 视频流路由"""
from fastapi import APIRouter, HTTPException

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
        pusher = rtsp_service._pushers.get(s.camera_id)
        items.append({
            "camera_id": s.camera_id,
            "name": s.name,
            "status": s.status,
            "rtsp_url": rtsp_service.get_rtsp_url(s.camera_id),
            "rtsp_active": pusher is not None and pusher._running,
        })
    return {"streams": items, "mediamtx_running": rtsp_service.is_mediamtx_running()}


@router.post("/{camera_id}/start-rtsp")
async def start_rtsp(camera_id: int):
    """
    确保 MediaMTX 运行，并为指定摄像头激活 RTSP 无损转推。
    摄像头流必须已在运行（on_raw_video_callback 才能拿到 HEVC 数据）。
    """
    state = camera_manager.get_state(camera_id)
    if not state or state.status != "running":
        raise HTTPException(400, "Camera stream is not running")

    if not rtsp_service.is_mediamtx_running():
        if not rtsp_service.start_mediamtx():
            raise HTTPException(503, "Failed to start MediaMTX")

    # 预先创建 FFmpeg 进程（首帧到来前就准备好管道）
    ok = rtsp_service.start_hevc_push(camera_id)
    return {
        "ok": ok,
        "rtsp_url": rtsp_service.get_rtsp_url(camera_id),
        "note": "HEVC passthrough (zero re-encode). Data flows via on_raw_video_callback.",
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
        "active_pushes": [
            cid for cid, p in rtsp_service._pushers.items()
            if p._running
        ],
    }


@router.post("/mediamtx/start")
async def start_mediamtx():
    ok = rtsp_service.start_mediamtx()
    return {"ok": ok, "running": rtsp_service.is_mediamtx_running()}


@router.post("/mediamtx/stop")
async def stop_mediamtx():
    rtsp_service.stop_mediamtx()
    return {"ok": True}
