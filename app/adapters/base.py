"""摄像头 Adapter 抽象接口"""
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional


class AbstractCameraAdapter(ABC):
    """
    所有品牌摄像头的统一接口。
    实现类负责：连接摄像头、持续推送 JPEG 帧、断开连接。
    """

    def __init__(self, camera_id: int, config: dict):
        self.camera_id = camera_id
        self.config = config

    @abstractmethod
    async def connect(
        self,
        on_jpeg_frame: Callable[[int, bytes], Awaitable[None]],
    ) -> None:
        """
        连接摄像头并持续推送帧。
        应在此方法内循环接收帧，通过 on_jpeg_frame(camera_id, jpeg_bytes) 回调传出。
        此方法应一直挂起直到被取消或连接断开。
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接，释放资源"""

    @property
    def brand(self) -> str:
        """返回品牌标识，如 'xiaomi', 'rtsp'"""
        return self.config.get("brand", "unknown")
