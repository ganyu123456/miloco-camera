"""系统监控 API：CPU / 内存 / GPU"""
import asyncio
from typing import List, Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/system", tags=["system"])


def _get_cpu_memory() -> dict:
    import psutil
    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu_percent,
        "memory": {
            "total_gb": round(mem.total / 1024**3, 2),
            "used_gb": round(mem.used / 1024**3, 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1024**3, 2),
            "used_gb": round(disk.used / 1024**3, 2),
            "percent": disk.percent,
        },
    }


def _get_gpu_info() -> List[dict]:
    """尝试通过 pynvml 获取 NVIDIA GPU 信息"""
    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temp = None
            try:
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                pass
            gpus.append({
                "index": i,
                "name": name,
                "gpu_percent": util.gpu,
                "memory_percent": round(mem_info.used / mem_info.total * 100, 1),
                "memory_used_mb": round(mem_info.used / 1024**2, 1),
                "memory_total_mb": round(mem_info.total / 1024**2, 1),
                "temperature": temp,
            })
        pynvml.nvmlShutdown()
        return gpus
    except Exception:
        return []


@router.get("/stats")
async def system_stats():
    loop = asyncio.get_running_loop()
    cpu_mem = await loop.run_in_executor(None, _get_cpu_memory)
    gpu_info = await loop.run_in_executor(None, _get_gpu_info)
    return {**cpu_mem, "gpus": gpu_info}


@router.get("/processes")
async def running_processes():
    """摄像头流和检测任务运行状态"""
    from app.services.camera_service import camera_manager
    from app.services.detection_service import detection_manager
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
        "detection_workers": list(detection_manager._workers.keys()),
        "rtsp_pushes": list(rtsp_service._ffmpeg_procs.keys()),
        "mediamtx": rtsp_service.is_mediamtx_running(),
    }
