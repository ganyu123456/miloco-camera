"""检测器抽象基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np


@dataclass
class Detection:
    """单次检测结果"""
    label: str
    confidence: float
    bbox: List[int]          # [x1, y1, x2, y2]
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class AbstractDetector(ABC):
    """所有检测器的统一接口"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._initialized = False

    def initialize(self) -> None:
        """加载模型/资源（懒初始化，首次使用前调用）"""
        self._initialized = True

    @abstractmethod
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """
        对一帧图像执行检测
        :param frame: BGR numpy array (H, W, 3)
        :return: 检测结果列表
        """

    def draw(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        """在帧上绘制检测结果（可选重写）"""
        import cv2
        result = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(result, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                result,
                f"{det.label} {det.confidence:.2f}",
                (x1, max(0, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
            )
        return result

    def release(self) -> None:
        """释放资源"""
        self._initialized = False
