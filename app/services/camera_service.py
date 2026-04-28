"""
摄像头管理服务（纯零解码网关模式）

每路摄像头只做两件事：
  1. 保持与摄像头的连接（小米 SDK / 标准 RTSP）
  2. 将原始码流无损推送到 MediaMTX（FFmpeg -c:v copy）

不做任何解码、不做 JPEG 编码、不保存帧数据。
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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
    _task: Optional[asyncio.Task] = field(default=None, repr=False)
    _adapter: object = field(default=None, repr=False)
    _miot_client: object = field(default=None, repr=False)


class CameraManager:
    """单例摄像头管理器，管理所有摄像头的流任务"""

    def __init__(self):
        self._cameras: Dict[int, CameraState] = {}

    def get_auth_info(self) -> Optional[dict]:
        import json
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
        """根据 brand 选择对应 adapter 执行流接入（零解码）"""
        try:
            if state.brand == "rtsp":
                adapter = self._create_rtsp_adapter(state)
            else:
                adapter = _XiaomiInlineAdapter(
                    camera_id=state.camera_id,
                    state=state,
                    quality=self._resolve_quality(state.video_quality),
                )

            state._adapter = adapter
            state.status = "running"
            logger.info(f"Camera {state.camera_id} ({state.did}) stream started [{state.brand}]")

            await adapter.connect()

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

    def _resolve_quality(self, video_quality: str):
        from miloco_sdk.utils.types import MIoTCameraVideoQuality
        quality_map = {
            "HIGH": MIoTCameraVideoQuality.HIGH,
            "LOW": MIoTCameraVideoQuality.LOW,
        }
        return quality_map.get(video_quality, MIoTCameraVideoQuality.HIGH)

    def _create_rtsp_adapter(self, state: CameraState):
        from app.adapters.rtsp import RtspAdapter
        return RtspAdapter(
            camera_id=state.camera_id,
            config={"rtsp_url": state.rtsp_url or ""},
        )


class _XiaomiInlineAdapter:
    """
    小米摄像头 Adapter — 纯零解码网关模式

    只注册 on_raw_video_callback，SDK 不在内部解码。
    原始 HEVC Annex B 码流直接经 PyAV NAL 切分后由 FFmpeg -c:v copy 推送到 MediaMTX。
    """

    def __init__(self, camera_id: int, state: CameraState, quality):
        self.camera_id = camera_id
        self._state = state
        self._quality = quality
        self._client = None

    async def connect(self):
        from miloco_sdk import XiaomiClient
        from miloco_sdk.cli.utils import get_auth_info
        from app.services.rtsp_service import rtsp_service

        state = self._state
        client = XiaomiClient()
        auth_info = get_auth_info(client)
        client.set_access_token(auth_info["access_token"])
        self._client = client.miot_camera_stream
        state._miot_client = self._client

        async def on_raw(did: str, data: bytes, ts: int, seq: int, channel: int):
            if not rtsp_service.is_mediamtx_running():
                return
            rtsp_service.push_hevc_packet(state.camera_id, data)

        await client.miot_camera_stream.run_stream(
            state.did,
            state.channel,
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
