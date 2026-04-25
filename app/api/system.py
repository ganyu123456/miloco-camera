"""系统监控 API：CPU / 内存 / 磁盘"""
import asyncio
from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])


def _get_cpu_memory() -> dict:
    import psutil
    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage("/")
        disk_info = {
            "total_gb": round(disk.total / 1024**3, 2),
            "used_gb": round(disk.used / 1024**3, 2),
            "percent": round(disk.percent, 1),
        }
    except Exception:
        disk_info = {"total_gb": 0, "used_gb": 0, "percent": 0}
    return {
        "cpu_percent": round(cpu_percent, 1),
        "memory": {
            "total_gb": round(mem.total / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": round(mem.percent, 1),
        },
        "disk": disk_info,
        "gpus": [],
    }


@router.get("/stats")
async def system_stats():
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_cpu_memory)
    except Exception as e:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0),
            "memory": {"total_gb": round(mem.total/1024**3, 2), "used_gb": round(mem.used/1024**3, 2), "percent": round(mem.percent, 1)},
            "disk": {"total_gb": 0, "used_gb": 0, "percent": 0},
            "gpus": [],
            "error": str(e),
        }


@router.get("/processes")
async def running_processes():
    """摄像头流运行状态"""
    from app.services.camera_service import camera_manager
    from app.services.rtsp_service import rtsp_service

    camera_states = [
        {
            "camera_id": s.camera_id,
            "name": s.name,
            "status": s.status,
            "error": s.error_msg,
        }
        for s in camera_manager.all_states()
    ]
    return {
        "cameras": camera_states,
        "rtsp_pushes": [
            cid for cid, p in rtsp_service._hevc_procs.items() if p.poll() is None
        ],
        "mediamtx": rtsp_service.is_mediamtx_running(),
    }
