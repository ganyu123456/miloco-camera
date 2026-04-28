"""摄像头 Adapter 抽象接口（零解码网关模式）"""
from abc import ABC, abstractmethod


class AbstractCameraAdapter(ABC):
    """
    所有品牌摄像头的统一接口。

    实现类负责：连接摄像头、将原始码流无损推送到 MediaMTX、断开连接。
    不涉及任何解码或 JPEG 编码操作。
    """

    def __init__(self, camera_id: int, config: dict):
        self.camera_id = camera_id
        self.config = config

    @abstractmethod
    async def connect(self) -> None:
        """
        连接摄像头并持续转推码流到 MediaMTX。
        此方法应一直挂起直到被取消或连接断开。
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接，释放资源"""

    @property
    def brand(self) -> str:
        """返回品牌标识，如 'xiaomi', 'rtsp'"""
        return self.config.get("brand", "unknown")
