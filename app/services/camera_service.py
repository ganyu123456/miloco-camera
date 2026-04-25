"""
摄像头管理服务
负责多路摄像头的接入、流管理和帧分发（支持多品牌 adapter）
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CameraState:
    camera_id: int
    name: str
    did: str
    brand: str = "xiaomi"
    channel: int = 0
    video_quality: str = "HIGH"
    rtsp_url: Optional[str] = None
    status: str = "stopped"       # stopped | starting | running | error
    error_msg: str = ""
    latest_frame: Optional[bytes] = None
    frame_event: asyncio.Event = field(default_factory=asyncio.Event)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)
    _adapter: object = field(default=None, repr=False)
    _miot_client: object = field(default=None, repr=False)
    _frame_callbacks: List[Callable] = field(default_factory=list, repr=False)

    def add_frame_callback(self, cb: Callable) -> None:
        if cb not in self._frame_callbacks:
            self._frame_callbacks.append(cb)

    def remove_frame_callback(self, cb: Callable) -> None:
        if cb in self._frame_callbacks:
            self._frame_callbacks.remove(cb)


class CameraManager:
    """单例摄像头管理器，管理所有摄像头的流任务"""

    def __init__(self):
        self._cameras: Dict[int, CameraState] = {}

    def get_auth_info(self) -> Optional[dict]:
        import json, time
        auth_file = settings.AUTH_INFO_PATH
        if not auth_file.exists():
            return None
        with open(auth_file, "r", encoding="utf-8") as f:
            info = json.load(f)
        return info

    def register(
        self,
        camera_id: int,
        name: str,
        did: str,
        brand: str = "xiaomi",
        channel: int = 0,
        video_quality: str = "HIGH",
        rtsp_url: Optional[str] = None,
    ) -> CameraState:
        if camera_id not in self._cameras:
            self._cameras[camera_id] = CameraState(
                camera_id=camera_id,
                name=name,
                did=did,
                brand=brand,
                channel=channel,
                video_quality=video_quality,
                rtsp_url=rtsp_url,
            )
        return self._cameras[camera_id]

    def unregister(self, camera_id: int) -> None:
        self._cameras.pop(camera_id, None)

    def get_state(self, camera_id: int) -> Optional[CameraState]:
        return self._cameras.get(camera_id)

    def all_states(self) -> List[CameraState]:
        return list(self._cameras.values())

    async def start(self, camera_id: int) -> bool:
        state = self._cameras.get(camera_id)
        if not state:
            logger.error(f"Camera {camera_id} not registered")
            return False
        if state.status == "running":
            return True

        state.status = "starting"
        state._task = asyncio.create_task(
            self._run_stream(state),
            name=f"camera-{camera_id}",
        )
        return True

    async def stop(self, camera_id: int) -> None:
        state = self._cameras.get(camera_id)
        if not state:
            return
        if state._task and not state._task.done():
            state._task.cancel()
            try:
                await state._task
            except (asyncio.CancelledError, Exception):
                pass
        state.status = "stopped"
        state.latest_frame = None
        logger.info(f"Camera {camera_id} stopped")

    async def start_all_enabled(self) -> None:
        """从数据库加载所有 enabled=True 的摄像头并启动流"""
        from app.database import AsyncSessionLocal
        from app.models.camera import Camera
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Camera).where(Camera.enabled == True))
            cameras = result.scalars().all()

        for cam in cameras:
            self.register(
                cam.id,
                cam.name,
                cam.did,
                brand=cam.brand,
                channel=cam.channel,
                video_quality=cam.video_quality,
                rtsp_url=cam.rtsp_url,
            )
            await self.start(cam.id)
            logger.info(f"Auto-started camera: {cam.name} ({cam.did}) [{cam.brand}]")

    async def _run_stream(self, state: CameraState) -> None:
        """根据 brand 选择对应 adapter 执行流接入"""
        async def on_jpeg_frame(camera_id: int, data: bytes) -> None:
            state.latest_frame = data
            state.frame_event.set()
            state.frame_event.clear()
            for cb in list(state._frame_callbacks):
                try:
                    await cb(camera_id, data)
                except Exception as e:
                    logger.warning(f"Frame callback error: {e}")

        try:
            if state.brand == "rtsp":
                adapter = self._create_rtsp_adapter(state)
            else:
                adapter = self._create_xiaomi_adapter(state)

            state._adapter = adapter
            state.status = "running"
            logger.info(f"Camera {state.camera_id} ({state.did}) stream started [{state.brand}]")

            await adapter.connect(on_jpeg_frame)

        except asyncio.CancelledError:
            logger.info(f"Camera {state.camera_id} stream cancelled")
        except Exception as e:
            state.status = "error"
            state.error_msg = str(e)
            logger.error(f"Camera {state.camera_id} stream error: {e}")
        finally:
            if state._adapter:
                try:
                    await state._adapter.disconnect()
                except Exception:
                    pass
                state._adapter = None
            if state.status not in ("stopped",):
                state.status = "error"

    def _create_xiaomi_adapter(self, state: CameraState):
        from miloco_sdk import XiaomiClient
        from miloco_sdk.cli.utils import get_auth_info
        from miloco_sdk.utils.types import MIoTCameraVideoQuality

        quality_map = {
            "HIGH": MIoTCameraVideoQuality.HIGH,
            "LOW": MIoTCameraVideoQuality.LOW,
        }
        quality = quality_map.get(state.video_quality, MIoTCameraVideoQuality.HIGH)

        return _XiaomiInlineAdapter(
            camera_id=state.camera_id,
            state=state,
            quality=quality,
        )

    def _create_rtsp_adapter(self, state: CameraState):
        from app.adapters.rtsp import RtspAdapter
        return RtspAdapter(
            camera_id=state.camera_id,
            config={"rtsp_url": state.rtsp_url or ""},
        )



class _XiaomiInlineAdapter:
    """
    小米摄像头 Adapter — 纯网关模式（零解码）

    双路回调设计：
      on_decode_jpg_callback → SDK 已解码的 JPEG，仅用于 Web MJPEG 预览（latest_frame）
      on_raw_video_callback  → 原始 HEVC Annex B 码流，直接管道给 FFmpeg -c:v copy 转推 RTSP
                               网关本身不做任何解码/重编码，全部运算压力留给 ai-detector
    """

    def __init__(self, camera_id: int, state: CameraState, quality):
        self.camera_id = camera_id
        self._state = state
        self._quality = quality
        self._client = None

    async def connect(self, on_jpeg_frame):
        from miloco_sdk import XiaomiClient
        from miloco_sdk.cli.utils import get_auth_info
        from app.services.rtsp_service import rtsp_service

        state = self._state
        client = XiaomiClient()
        auth_info = get_auth_info(client)
        client.set_access_token(auth_info["access_token"])
        self._client = client.miot_camera_stream
        state._miot_client = self._client

        # ── 路径 1：Web 预览（JPEG，SDK 自解码，不经过我们） ────────
        async def on_jpg(did: str, data: bytes, ts: int, channel: int):
            await on_jpeg_frame(state.camera_id, data)

        # ── 路径 2：RTSP 无损转推（原始 HEVC，-c:v copy，零解码） ──
        async def on_raw(did: str, data: bytes, ts: int, seq: int, channel: int):
            if not rtsp_service.is_mediamtx_running():
                return
            # 首包到来时惰性启动该路摄像头的 HEVC 推流进程
            if state.camera_id not in rtsp_service._hevc_procs:
                rtsp_service.start_hevc_push(state.camera_id)
            rtsp_service.push_hevc_packet(state.camera_id, data)

        await client.miot_camera_stream.run_stream(
            state.did,
            state.channel,
            on_decode_jpg_callback=on_jpg,
            on_raw_video_callback=on_raw,
            video_quality=self._quality,
        )
        await client.miot_camera_stream.wait_for_data()

    async def disconnect(self):
        if self._client:
            try:
                await self._client.cleanup()
            except Exception:
                pass
            self._client = None
            if self._state:
                self._state._miot_client = None


camera_manager = CameraManager()
