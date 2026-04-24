"""
AI 视频网关 - FastAPI 应用入口
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _get_static_dir() -> Path:
    """
    PyInstaller --onefile 时资源在 sys._MEIPASS/web/static；
    普通运行时在 app/web/static（相对于本文件）。
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "web" / "static"
    return Path(__file__).parent / "web" / "static"


STATIC_DIR = _get_static_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──────────────────────────────────────────────────
    logger.info("Initializing database...")
    await init_db()

    logger.info("Starting camera streams...")
    from app.services.camera_service import camera_manager
    await camera_manager.start_all_enabled()

    logger.info("Starting detection workers...")
    from app.services.detection_service import detection_manager
    await detection_manager.start_all_enabled()

    logger.info("AI Gateway started")
    yield

    # ── 关闭 ──────────────────────────────────────────────────
    logger.info("Stopping camera streams...")
    from app.services.camera_service import camera_manager
    for state in camera_manager.all_states():
        await camera_manager.stop(state.camera_id)

    logger.info("Stopping RTSP service...")
    from app.services.rtsp_service import rtsp_service
    rtsp_service.stop_all()

    logger.info("AI Gateway shutdown complete")


app = FastAPI(
    title="AI 视频网关",
    description="小米摄像头 AI 检测与管理平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 注册 API 路由
from app.api.cameras import router as cameras_router
from app.api.detections import router as detections_router
from app.api.alerts import router as alerts_router
from app.api.streams import router as streams_router
from app.api.system import router as system_router
from app.api.web_routes import router as web_router

app.include_router(cameras_router)
app.include_router(detections_router)
app.include_router(alerts_router)
app.include_router(streams_router)
app.include_router(system_router)
app.include_router(web_router)


if __name__ == "__main__":
    import uvicorn
    # PyInstaller 冻结环境不支持字符串模块路径和 reload，直接传 app 对象
    _reload = False if getattr(sys, 'frozen', False) else settings.DEBUG
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=_reload,
        log_level="info",
    )
