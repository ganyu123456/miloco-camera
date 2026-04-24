"""YOLO 目标检测器（基于 ultralytics YOLOv8/v11）"""
import logging
from typing import Any, Dict, List, Optional

import numpy as np

from app.detectors.base import AbstractDetector, Detection
from app.config import settings

logger = logging.getLogger(__name__)


class YoloDetector(AbstractDetector):
    """
    YOLOv8/v11 目标检测器
    config:
        model: str        - 模型文件路径或名称，如 "yolo11n.pt"
        confidence: float - 置信度阈值，默认 0.5
        iou: float        - NMS IoU 阈值，默认 0.45
        classes: list     - 只检测指定类别名称，如 ["person", "car"]，空列表=检测全部
        device: str       - "cpu" | "cuda" | "0"，默认自动
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._model = None
        self._class_names: Optional[List[str]] = None

    def initialize(self) -> None:
        from ultralytics import YOLO
        model_path = self.config.get("model", settings.YOLO_MODEL)
        device = self.config.get("device", "")
        logger.info(f"Loading YOLO model: {model_path}")
        self._model = YOLO(model_path)
        if device:
            self._model.to(device)
        self._initialized = True
        logger.info("YOLO model loaded")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self._initialized or self._model is None:
            self.initialize()

        confidence = float(self.config.get("confidence", settings.YOLO_CONFIDENCE))
        iou = float(self.config.get("iou", 0.45))
        filter_classes: List[str] = self.config.get("classes", [])

        results = self._model.predict(
            frame,
            conf=confidence,
            iou=iou,
            verbose=False,
        )

        detections: List[Detection] = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                label = r.names[cls_id]
                # 按类别过滤
                if filter_classes and label not in filter_classes:
                    continue
                conf = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                detections.append(Detection(
                    label=label,
                    confidence=conf,
                    bbox=[x1, y1, x2, y2],
                    metadata={"cls_id": cls_id},
                ))
        return detections

    def release(self) -> None:
        self._model = None
        self._initialized = False
