"""
RTSP 分发服务
- 启动 MediaMTX 子进程作为 RTSP 服务器
- 使用 FFmpeg 将摄像头帧推送为 RTSP 流
- 同时提供 MJPEG HTTP 流作为备选
"""
import asyncio
import logging
import subprocess
import threading
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class RTSPService:

    def __init__(self):
        self._mediamtx_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_procs: Dict[int, subprocess.Popen] = {}
        self._running = False

    # ── MediaMTX 管理 ─────────────────────────────────────────
    def start_mediamtx(self) -> bool:
        """启动 MediaMTX RTSP 服务器"""
        if self._mediamtx_proc and self._mediamtx_proc.poll() is None:
            return True
        try:
            self._mediamtx_proc = subprocess.Popen(
                [settings.MEDIAMTX_BIN],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._running = True
            logger.info(f"MediaMTX started (PID {self._mediamtx_proc.pid})")
            return True
        except FileNotFoundError:
            logger.warning(
                "MediaMTX not found. RTSP push disabled. "
                "Install from https://github.com/bluenviron/mediamtx/releases"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to start MediaMTX: {e}")
            return False

    def stop_mediamtx(self) -> None:
        if self._mediamtx_proc and self._mediamtx_proc.poll() is None:
            self._mediamtx_proc.terminate()
            self._mediamtx_proc.wait(timeout=5)
        self._mediamtx_proc = None
        self._running = False

    def is_mediamtx_running(self) -> bool:
        return self._mediamtx_proc is not None and self._mediamtx_proc.poll() is None

    # ── FFmpeg RTSP 推流 ───────────────────────────────────────
    def start_push(self, camera_id: int, width: int = 1920, height: int = 1080, fps: int = 15) -> bool:
        """为指定摄像头启动 FFmpeg RTSP 推流进程"""
        if camera_id in self._ffmpeg_procs:
            proc = self._ffmpeg_procs[camera_id]
            if proc.poll() is None:
                return True

        rtsp_url = self.get_rtsp_url(camera_id)
        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo",
            "-pixel_format", "bgr24",
            "-video_size", f"{width}x{height}",
            "-framerate", str(fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-f", "rtsp",
            rtsp_url,
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._ffmpeg_procs[camera_id] = proc
            logger.info(f"FFmpeg RTSP push started for camera {camera_id}: {rtsp_url}")
            return True
        except FileNotFoundError:
            logger.warning("ffmpeg not found; RTSP push disabled")
            return False
        except Exception as e:
            logger.error(f"Failed to start ffmpeg for camera {camera_id}: {e}")
            return False

    def stop_push(self, camera_id: int) -> None:
        proc = self._ffmpeg_procs.pop(camera_id, None)
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=5)

    def push_frame(self, camera_id: int, bgr_frame_bytes: bytes) -> None:
        """向 FFmpeg stdin 写入原始 BGR 帧（在帧回调中调用）"""
        proc = self._ffmpeg_procs.get(camera_id)
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(bgr_frame_bytes)
                proc.stdin.flush()
            except BrokenPipeError:
                logger.warning(f"FFmpeg pipe broken for camera {camera_id}, restarting...")
                self.stop_push(camera_id)
            except Exception as e:
                logger.debug(f"RTSP push error camera {camera_id}: {e}")

    # ── URL 工具 ───────────────────────────────────────────────
    def get_rtsp_url(self, camera_id: int) -> str:
        return f"rtsp://{settings.RTSP_HOST}:{settings.RTSP_PORT}/camera_{camera_id}"

    def get_all_rtsp_urls(self) -> Dict[int, str]:
        return {cid: self.get_rtsp_url(cid) for cid in self._ffmpeg_procs}

    def stop_all(self) -> None:
        for cid in list(self._ffmpeg_procs.keys()):
            self.stop_push(cid)
        self.stop_mediamtx()


rtsp_service = RTSPService()
