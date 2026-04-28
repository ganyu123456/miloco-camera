"""
标准 RTSP 零解码透传 Adapter（海康、大华等支持标准 RTSP 协议的摄像头）

数据流：
  源 RTSP 摄像头 → FFmpeg -c:v copy → MediaMTX

FFmpeg 直接以 -c:v copy 做协议转封装，不解码、不重编码，
CPU 占用接近零，带宽即为唯一瓶颈。
"""
import asyncio
import logging
import subprocess
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_RETRY_DELAY = 3.0


class RtspAdapter:
    """
    将源 RTSP 地址通过 FFmpeg -c:v copy 转推到 MediaMTX。

    config 字段:
        rtsp_url: str  - 源摄像头 RTSP 地址，如 rtsp://admin:pass@192.168.1.10:554/stream
    """

    def __init__(self, camera_id: int, config: dict):
        self.camera_id = camera_id
        self.config = config
        self._running = False

    async def connect(self) -> None:
        """持续运行转推循环，断线后自动重连，直到被取消。"""
        src_url = self.config.get("rtsp_url", "")
        if not src_url:
            raise ValueError(f"Camera {self.camera_id}: rtsp_url is empty")

        push_url = f"rtsp://127.0.0.1:{settings.RTSP_PORT}/camera_{self.camera_id}"
        self._running = True

        logger.info(f"RtspAdapter cam{self.camera_id}: {src_url} → {push_url}")

        while self._running:
            try:
                await self._run_ffmpeg(src_url, push_url)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"RtspAdapter cam{self.camera_id} error: {e}")

            if self._running:
                logger.info(f"RtspAdapter cam{self.camera_id}: reconnecting in {_RETRY_DELAY}s")
                await asyncio.sleep(_RETRY_DELAY)

    async def disconnect(self) -> None:
        self._running = False

    async def _run_ffmpeg(self, src_url: str, push_url: str) -> None:
        """启动一个 FFmpeg 子进程做零解码 RTSP 透传，直到进程退出或被取消。"""
        cmd = [
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", src_url,
            "-c", "copy",           # 视频+音频全部 copy，零解码零重编码
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            push_url,
        ]

        proc: Optional[asyncio.subprocess.Process] = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info(f"RtspAdapter cam{self.camera_id} FFmpeg started (pid={proc.pid})")
            await proc.wait()
            if proc.returncode != 0:
                logger.warning(
                    f"RtspAdapter cam{self.camera_id} FFmpeg exited (code={proc.returncode})"
                )
        except asyncio.CancelledError:
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
            raise

    @property
    def brand(self) -> str:
        return "rtsp"
