"""
RTSP 分发服务
- 启动 MediaMTX 子进程作为 RTSP 服务器
- 将摄像头原始 HEVC 码流通过 FFmpeg -c:v copy 无损转推为 RTSP（零解码零重编码）
- MJPEG HTTP 预览由 camera_service 的 latest_frame 独立提供，与 RTSP 路径完全解耦
"""
import logging
import subprocess
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class RTSPService:

    def __init__(self):
        self._mediamtx_proc: Optional[subprocess.Popen] = None
        # camera_id → FFmpeg HEVC passthrough 进程
        self._hevc_procs: Dict[int, subprocess.Popen] = {}

    # ── MediaMTX 管理 ─────────────────────────────────────────

    def start_mediamtx(self) -> bool:
        """启动 MediaMTX RTSP 服务器进程"""
        if self._mediamtx_proc and self._mediamtx_proc.poll() is None:
            return True
        try:
            self._mediamtx_proc = subprocess.Popen(
                [settings.MEDIAMTX_BIN],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
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
            try:
                self._mediamtx_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._mediamtx_proc.kill()
        self._mediamtx_proc = None

    def is_mediamtx_running(self) -> bool:
        return self._mediamtx_proc is not None and self._mediamtx_proc.poll() is None

    # ── HEVC 无损转推 ──────────────────────────────────────────

    def start_hevc_push(self, camera_id: int) -> bool:
        """
        启动 FFmpeg 进程，将 stdin 接收的原始 HEVC Annex B 码流
        无损（-c:v copy）推送到 MediaMTX。

        -bsf:v dump_extra 确保每个关键帧前重复写入 SPS/PPS，
        使后接入的 RTSP 客户端（如 ai-detector）也能立即解码。
        """
        proc = self._hevc_procs.get(camera_id)
        if proc and proc.poll() is None:
            return True  # 已在运行

        rtsp_url = self.get_rtsp_url(camera_id)
        cmd = [
            "ffmpeg", "-y",
            "-f", "hevc",          # 输入格式：原始 HEVC Annex B 码流
            "-i", "pipe:0",        # 从 stdin 读取
            "-c:v", "copy",        # 零解码零重编码，完整保留原始画质
            "-bsf:v", "dump_extra",# 每关键帧重复 SPS/PPS（方便客户端随时接入）
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._hevc_procs[camera_id] = proc
            logger.info(f"HEVC passthrough push started for camera {camera_id}: {rtsp_url}")
            return True
        except FileNotFoundError:
            logger.warning("ffmpeg not found; RTSP push disabled")
            return False
        except Exception as e:
            logger.error(f"Failed to start ffmpeg for camera {camera_id}: {e}")
            return False

    def push_hevc_packet(self, camera_id: int, data: bytes) -> None:
        """将一个 HEVC NAL 包写入对应的 FFmpeg stdin。"""
        proc = self._hevc_procs.get(camera_id)
        if proc is None or proc.poll() is not None:
            # 进程不存在或已退出，尝试重启
            logger.debug(f"FFmpeg HEVC proc for camera {camera_id} not running, restarting...")
            self._hevc_procs.pop(camera_id, None)
            if not self.start_hevc_push(camera_id):
                return
            proc = self._hevc_procs.get(camera_id)
            if proc is None:
                return

        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except BrokenPipeError:
            logger.warning(f"FFmpeg HEVC pipe broken for camera {camera_id}, will restart on next packet")
            self._hevc_procs.pop(camera_id, None)
        except Exception as e:
            logger.debug(f"HEVC push error camera {camera_id}: {e}")

    def stop_push(self, camera_id: int) -> None:
        proc = self._hevc_procs.pop(camera_id, None)
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ── URL 工具 ───────────────────────────────────────────────

    def get_rtsp_url(self, camera_id: int) -> str:
        return f"rtsp://{settings.RTSP_HOST}:{settings.RTSP_PORT}/camera_{camera_id}"

    def get_all_rtsp_urls(self) -> Dict[int, str]:
        return {cid: self.get_rtsp_url(cid) for cid in self._hevc_procs}

    def stop_all(self) -> None:
        for cid in list(self._hevc_procs.keys()):
            self.stop_push(cid)
        self.stop_mediamtx()


rtsp_service = RTSPService()
