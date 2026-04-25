"""小米摄像头 Adapter（基于 libmiot_camera_lite 私有协议）"""
import logging
from typing import Awaitable, Callable, Optional

from app.adapters.base import AbstractCameraAdapter

logger = logging.getLogger(__name__)


class XiaomiAdapter(AbstractCameraAdapter):
    """
    通过小米 MIoT SDK 接入摄像头。
    config 字段:
        did: str          - 设备 ID
        channel: int      - 通道，默认 0
        video_quality: str - HIGH / LOW，默认 HIGH
    """

    def __init__(self, camera_id: int, config: dict):
        super().__init__(camera_id, config)
        self._stream_client = None

    async def connect(
        self,
        on_jpeg_frame: Callable[[int, bytes], Awaitable[None]],
    ) -> None:
        from miloco_sdk import XiaomiClient
        from miloco_sdk.cli.utils import get_auth_info
        from miloco_sdk.utils.types import MIoTCameraVideoQuality

        quality_map = {
            "HIGH": MIoTCameraVideoQuality.HIGH,
            "LOW": MIoTCameraVideoQuality.LOW,
        }
        did = self.config["did"]
        channel = self.config.get("channel", 0)
        quality = quality_map.get(self.config.get("video_quality", "HIGH"), MIoTCameraVideoQuality.HIGH)

        client = XiaomiClient()
        auth_info = get_auth_info(client)
        client.set_access_token(auth_info["access_token"])
        self._stream_client = client.miot_camera_stream

        async def on_jpg(did_: str, data: bytes, ts: int, channel_: int):
            await on_jpeg_frame(self.camera_id, data)

        async def on_raw(did_: str, data: bytes, ts: int, seq: int, channel_: int):
            # 回退路径：macOS 版本库走此回调，PyAV 解码
            frame = await self._decode_hevc(data)
            if frame:
                await on_jpeg_frame(self.camera_id, frame)

        await self._stream_client.run_stream(
            did,
            channel,
            on_decode_jpg_callback=on_jpg,
            on_raw_video_callback=on_raw,
            video_quality=quality,
        )
        await self._stream_client.wait_for_data()

    async def _decode_hevc(self, data: bytes) -> Optional[bytes]:
        try:
            import cv2
            import numpy as np
            from av.packet import Packet
            from av.video.codeccontext import VideoCodecContext

            if not hasattr(self, '_decoder'):
                self._decoder = VideoCodecContext.create("hevc", "r")
            pkt = Packet(data)
            for frame in self._decoder.decode(pkt):
                bgr = frame.to_ndarray(format="bgr24")
                ret, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    return jpeg.tobytes()
        except Exception:
            pass
        return None

    async def disconnect(self) -> None:
        if self._stream_client:
            try:
                await self._stream_client.cleanup()
            except Exception:
                pass
            self._stream_client = None

    @property
    def brand(self) -> str:
        return "xiaomi"
