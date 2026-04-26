"""
RTSP 分发服务
- 启动 MediaMTX 子进程作为 RTSP 服务器
- 使用 PyAV (libavcodec hevc bitstream parser) 正确切分 NAL 单元边界，
  再通过 FFmpeg 无损推送到 MediaMTX（零解码零重编码）

数据流：
  async on_raw → queue → [pusher 线程] → PyAV hevc_parser → FFmpeg pipe → MediaMTX

PyAV 的 av_parser_parse2 正确识别 HEVC NAL 单元边界（处理 SDK 每次回调可能
包含多个 NAL 单元的情况），输出标准 Annex B 格式的独立 NAL 包，解决 FFmpeg
直接收到未切分数据时出现 "PPS id out of range" 的问题。
"""
import logging
import queue
import subprocess
import threading
import time
from typing import Dict, List, Optional

import av

from app.config import settings

logger = logging.getLogger(__name__)

_QUEUE_MAX = 300       # 最多缓存约 10s 帧数（30fps × 10s）
_WARMUP_PKTS = 8       # 启动 FFmpeg 前至少解析的包数（确保 parser 已处理 SPS/PPS）
_RETRY_DELAY = 2.0     # 推流失败后重试间隔（秒）


class _CameraPusher:
    """
    单路摄像头的推流管理器（独立后台线程）。

    PyAV 的 hevc bitstream parser 将 SDK 原始数据正确切分为独立 NAL 单元，
    每个 NAL 单元以 Annex B start code 开头，FFmpeg 可以准确解析 SPS/PPS，
    从而生成合法的 RTSP SDP，MediaMTX 不再返回 400。
    """

    def __init__(self, camera_id: int, push_url: str, public_url: str):
        self._camera_id = camera_id
        self._push_url = push_url
        self._public_url = public_url
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name=f"rtsp-push-cam{camera_id}",
            daemon=True,
        )
        self._thread.start()

    def push(self, data: bytes) -> None:
        """投入原始 HEVC 数据（非阻塞，队满时丢帧而不阻塞事件循环）。"""
        if not self._running:
            return
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            pass

    def stop(self) -> None:
        """停止推流线程。"""
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    # ── 线程内部 ───────────────────────────────────────────────

    def _run(self) -> None:
        while self._running:
            self._push_session()
            if self._running:
                logger.info(f"cam{self._camera_id} pusher: reconnecting in {_RETRY_DELAY}s")
                time.sleep(_RETRY_DELAY)
        logger.info(f"cam{self._camera_id} pusher thread stopped")

    def _push_session(self) -> None:
        """一次完整的推流会话（连接 → 推流 → 断开）。"""
        codec_ctx: Optional[av.CodecContext] = None
        proc: Optional[subprocess.Popen] = None
        try:
            codec_ctx = av.CodecContext.create("hevc", "r")

            # ── 阶段 1：热身，缓冲足够的 parsed 包让 FFmpeg 看到 SPS/PPS ──
            parsed_buf: List[bytes] = []
            while self._running and len(parsed_buf) < _WARMUP_PKTS:
                raw = self._get_data()
                if raw is None:
                    return
                for pkt in self._parse(codec_ctx, raw):
                    parsed_buf.append(bytes(pkt))

            if not parsed_buf:
                return

            # ── 阶段 2：启动 FFmpeg 子进程（RTSP 推流）──
            cmd = [
                "ffmpeg", "-y",
                "-f", "hevc",           # 输入：Annex B 码流
                "-i", "pipe:0",         # 从 stdin 读取（已由 PyAV 正确分帧）
                "-c:v", "copy",         # 零解码零重编码
                "-bsf:v", "dump_extra", # 每关键帧重复 SPS/PPS
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                self._push_url,
            ]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                f"cam{self._camera_id} push started: "
                f"{self._push_url} → public: {self._public_url}"
            )

            # 刷出热身缓冲
            for data in parsed_buf:
                proc.stdin.write(data)
            proc.stdin.flush()
            parsed_buf.clear()

            # ── 阶段 3：持续推流 ──
            while self._running:
                if proc.poll() is not None:
                    logger.warning(
                        f"cam{self._camera_id} FFmpeg exited (code {proc.returncode})"
                    )
                    return

                raw = self._get_data()
                if raw is None:
                    return

                for pkt in self._parse(codec_ctx, raw):
                    data = bytes(pkt)
                    if not data:
                        continue
                    try:
                        proc.stdin.write(data)
                        proc.stdin.flush()
                    except BrokenPipeError:
                        logger.warning(f"cam{self._camera_id} pipe broken, reconnecting")
                        return

        except Exception as e:
            logger.warning(f"cam{self._camera_id} push session error: {e}")
        finally:
            if proc is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            if codec_ctx is not None:
                try:
                    codec_ctx.close()
                except Exception:
                    pass

    def _get_data(self) -> Optional[bytes]:
        """从队列取数据，超时或停止时返回 None。"""
        while self._running:
            try:
                return self._queue.get(timeout=5)
            except queue.Empty:
                continue
        return None

    @staticmethod
    def _parse(ctx: av.CodecContext, data: bytes) -> List[av.Packet]:
        """用 libavcodec hevc bitstream parser 切分 NAL 单元，返回非空包列表。"""
        try:
            return [p for p in ctx.parse(data) if p.size > 0]
        except Exception:
            return []


class RTSPService:

    def __init__(self):
        self._mediamtx_proc: Optional[subprocess.Popen] = None
        # camera_id → 推流管理器
        self._pushers: Dict[int, _CameraPusher] = {}

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
        为指定摄像头启动推流管理器（_CameraPusher）。

        推流管理器在独立线程中运行：
          1. 使用 PyAV hevc_parser 正确切分 NAL 单元
          2. 将 Annex B 格式的 NAL 包通过管道喂给 FFmpeg
          3. FFmpeg 用 -c:v copy 无损推送到 MediaMTX
        """
        if camera_id in self._pushers:
            return True

        push_url = f"rtsp://127.0.0.1:{settings.RTSP_PORT}/camera_{camera_id}"
        pusher = _CameraPusher(
            camera_id=camera_id,
            push_url=push_url,
            public_url=self.get_rtsp_url(camera_id),
        )
        self._pushers[camera_id] = pusher
        return True

    def push_hevc_packet(self, camera_id: int, data: bytes) -> None:
        """将一个原始 HEVC 数据包投入对应摄像头的推流队列。"""
        pusher = self._pushers.get(camera_id)
        if pusher is None:
            self.start_hevc_push(camera_id)
            pusher = self._pushers.get(camera_id)
        if pusher:
            pusher.push(data)

    def stop_push(self, camera_id: int) -> None:
        pusher = self._pushers.pop(camera_id, None)
        if pusher:
            pusher.stop()

    # ── URL 工具 ───────────────────────────────────────────────

    def get_rtsp_url(self, camera_id: int) -> str:
        return f"rtsp://{settings.RTSP_HOST}:{settings.RTSP_PORT}/camera_{camera_id}"

    def get_all_rtsp_urls(self) -> Dict[int, str]:
        return {cid: self.get_rtsp_url(cid) for cid in self._pushers}

    def stop_all(self) -> None:
        for cid in list(self._pushers.keys()):
            self.stop_push(cid)
        self.stop_mediamtx()


rtsp_service = RTSPService()
