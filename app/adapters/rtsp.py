"""标准 RTSP Adapter（海康、大华等支持标准 RTSP 协议的摄像头）"""
import asyncio
import logging
from typing import Awaitable, Callable

from app.adapters.base import AbstractCameraAdapter

logger = logging.getLogger(__name__)


class RtspAdapter(AbstractCameraAdapter):
    """
    通过标准 RTSP 协议接入摄像头，使用 PyAV 拉流解码。
    config 字段:
        rtsp_url: str     - 完整 RTSP 地址，如 rtsp://admin:pass@192.168.1.10:554/stream
        fps_limit: int    - 限制帧率，默认 15（0=不限制）
    """

    def __init__(self, camera_id: int, config: dict):
        super().__init__(camera_id, config)
        self._running = False

    async def connect(
        self,
        on_jpeg_frame: Callable[[int, bytes], Awaitable[None]],
    ) -> None:
        import av
        import cv2
        import numpy as np

        rtsp_url = self.config["rtsp_url"]
        fps_limit = int(self.config.get("fps_limit", 15))
        frame_interval = 1.0 / fps_limit if fps_limit > 0 else 0

        self._running = True
        logger.info(f"RtspAdapter camera {self.camera_id}: connecting to {rtsp_url}")

        loop = asyncio.get_running_loop()

        def _pull_frames():
            try:
                container = av.open(
                    rtsp_url,
                    options={"rtsp_transport": "tcp", "stimeout": "5000000"},
                )
                import time
                last_ts = 0.0
                for packet in container.demux(video=0):
                    if not self._running:
                        break
                    for frame in packet.decode():
                        if not self._running:
                            break
                        now = time.monotonic()
                        if frame_interval > 0 and now - last_ts < frame_interval:
                            continue
                        last_ts = now
                        bgr = frame.to_ndarray(format="bgr24")
                        ret, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if ret:
                            asyncio.run_coroutine_threadsafe(
                                on_jpeg_frame(self.camera_id, jpeg.tobytes()),
                                loop,
                            )
                container.close()
            except Exception as e:
                logger.error(f"RtspAdapter camera {self.camera_id} error: {e}")

        await loop.run_in_executor(None, _pull_frames)

    async def disconnect(self) -> None:
        self._running = False

    @property
    def brand(self) -> str:
        return "rtsp"
