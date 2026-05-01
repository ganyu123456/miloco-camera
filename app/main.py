"""
流媒体网关 - FastAPI 应用入口
"""
import asyncio
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
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "web" / "static"
    return Path(__file__).parent / "web" / "static"


STATIC_DIR = _get_static_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──────────────────────────────────────────────────
    logger.info("Initializing database...")
    await init_db()

    logger.info("Starting MediaMTX (RTSP server)...")
    from app.services.rtsp_service import rtsp_service
    if rtsp_service.start_mediamtx():
        logger.info(f"MediaMTX listening on RTSP port {settings.RTSP_PORT}")
    else:
        logger.warning("MediaMTX not available; RTSP push will be disabled")

    logger.info("Starting camera streams...")
    from app.services.camera_service import camera_manager
    await camera_manager.start_all_enabled()

    logger.info("Starting token refresh service...")
    from app.services.token_service import token_refresh_loop
    token_task = asyncio.create_task(token_refresh_loop(), name="token-refresh")

    logger.info("Stream Gateway started")
    yield

    # ── 关闭 ──────────────────────────────────────────────────
    logger.info("Stopping token refresh service...")
    token_task.cancel()
    try:
        await token_task
    except asyncio.CancelledError:
        pass

    logger.info("Stopping camera streams...")
    from app.services.camera_service import camera_manager
    for state in camera_manager.all_states():
        await camera_manager.stop(state.camera_id)

    logger.info("Stopping RTSP service...")
    from app.services.rtsp_service import rtsp_service
    rtsp_service.stop_all()

    logger.info("Stream Gateway shutdown complete")


app = FastAPI(
    title="流媒体网关",
    description="小米摄像头流媒体接入网关，支持多厂商摄像头统一转为标准 RTSP 输出",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

from app.api.cameras import router as cameras_router
from app.api.streams import router as streams_router
from app.api.system import router as system_router
from app.api.web_routes import router as web_router

app.include_router(cameras_router)
app.include_router(streams_router)
app.include_router(system_router)
app.include_router(web_router)


if __name__ == "__main__":
    import uvicorn
    _reload = False if getattr(sys, 'frozen', False) else settings.DEBUG
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=_reload,
        log_level="info",
    )
