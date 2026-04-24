"""
OpenCV 检测器
- IntrusionDetector  : 多边形 ROI 入侵检测（基于背景差分 + 轮廓）
- CollisionDetector : 越线检测（虚拟绊线）
"""
import logging
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from app.detectors.base import AbstractDetector, Detection

logger = logging.getLogger(__name__)


class IntrusionDetector(AbstractDetector):
    """
    入侵区域检测
    config:
        roi: list[list[int]]  - 多边形顶点 [[x,y], ...]，坐标为像素绝对值
        min_area: int         - 最小轮廓面积，过滤噪声，默认 500
        sensitivity: float    - 背景差分阈值，0-255，值越小越灵敏，默认 50
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._bg_subtractor = None
        self._roi_pts: np.ndarray = None
        self._roi_mask: np.ndarray = None
        self._frame_size: Tuple[int, int] = (0, 0)

    def initialize(self) -> None:
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=50, detectShadows=False
        )
        self._initialized = True

    def _build_mask(self, h: int, w: int) -> None:
        roi_raw = self.config.get("roi", [])
        if not roi_raw:
            # 全图作为 ROI
            self._roi_pts = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.int32)
        else:
            self._roi_pts = np.array(roi_raw, dtype=np.int32)
        self._roi_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(self._roi_mask, [self._roi_pts], 255)
        self._frame_size = (h, w)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self._initialized:
            self.initialize()

        h, w = frame.shape[:2]
        if self._frame_size != (h, w):
            self._build_mask(h, w)

        sensitivity = int(self.config.get("sensitivity", 50))
        min_area = int(self.config.get("min_area", 500))

        fg_mask = self._bg_subtractor.apply(frame)
        # 只保留 ROI 区域
        roi_fg = cv2.bitwise_and(fg_mask, fg_mask, mask=self._roi_mask)
        _, thresh = cv2.threshold(roi_fg, sensitivity, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: List[Detection] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, cw, ch = cv2.boundingRect(cnt)
            detections.append(Detection(
                label="intrusion",
                confidence=min(1.0, area / (w * h)),
                bbox=[x, y, x + cw, y + ch],
                metadata={"area": int(area)},
            ))
        return detections

    def draw(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        result = frame.copy()
        if self._roi_pts is not None:
            cv2.polylines(result, [self._roi_pts], True, (255, 200, 0), 2)
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(result, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(result, "INTRUSION", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return result


class CollisionDetector(AbstractDetector):
    """
    越线（绊线）检测
    config:
        lines: list[list[list[int]]]  - 虚拟绊线列表，每条线为 [[x1,y1],[x2,y2]]
        direction: "any"|"up"|"down"  - 检测方向，默认 "any"
        min_area: int                 - 最小运动面积，默认 300
        sensitivity: float            - 背景差分阈值，默认 40
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._bg_subtractor = None
        self._lines: List[List[List[int]]] = []
        self._frame_size: Tuple[int, int] = (0, 0)
        self._prev_centroids: List[Tuple[int, int]] = []

    def initialize(self) -> None:
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=40, detectShadows=False
        )
        self._lines = self.config.get("lines", [])
        self._initialized = True

    @staticmethod
    def _side(px: int, py: int, x1: int, y1: int, x2: int, y2: int) -> float:
        return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if not self._initialized:
            self.initialize()
        if not self._lines:
            return []

        min_area = int(self.config.get("min_area", 300))
        sensitivity = int(self.config.get("sensitivity", 40))

        fg = self._bg_subtractor.apply(frame)
        _, thresh = cv2.threshold(fg, sensitivity, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        curr_centroids: List[Tuple[int, int]] = []
        for cnt in contours:
            if cv2.contourArea(cnt) < min_area:
                continue
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            curr_centroids.append((cx, cy))

        detections: List[Detection] = []
        for (cx, cy) in curr_centroids:
            for (px, py) in self._prev_centroids:
                for line in self._lines:
                    if len(line) < 2:
                        continue
                    (x1, y1), (x2, y2) = line[0], line[1]
                    s_prev = self._side(px, py, x1, y1, x2, y2)
                    s_curr = self._side(cx, cy, x1, y1, x2, y2)
                    if s_prev * s_curr < 0:
                        x, y, cw, ch = cv2.boundingRect(
                            np.array([[cx - 20, cy - 20], [cx + 20, cy + 20]])
                        )
                        detections.append(Detection(
                            label="collision",
                            confidence=0.9,
                            bbox=[max(0, x), max(0, y), x + cw, y + ch],
                            metadata={"centroid": [cx, cy]},
                        ))

        self._prev_centroids = curr_centroids
        return detections

    def draw(self, frame: np.ndarray, detections: List[Detection]) -> np.ndarray:
        result = frame.copy()
        for line in self._lines:
            if len(line) >= 2:
                (x1, y1), (x2, y2) = line[0], line[1]
                cv2.line(result, (x1, y1), (x2, y2), (0, 255, 255), 2)
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(result, (x1, y1), (x2, y2), (0, 165, 255), 2)
            cv2.putText(result, "CROSSING", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
        return result
