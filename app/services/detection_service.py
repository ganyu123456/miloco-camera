"""
检测算法调度服务
订阅摄像头帧，按配置运行各检测器，触发报警
"""
import asyncio
import io
import logging
from typing import Dict, List, Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


class DetectionWorker:
    """单个摄像头的检测工作者"""

    def __init__(self, camera_id: int):
        self.camera_id = camera_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1)  # 只保留最新帧，有间隔限频
        self._task: Optional[asyncio.Task] = None
        self._detectors: List = []        # AbstractDetector 实例列表
        self._detection_configs: List[dict] = []

    async def push_frame(self, camera_id: int, frame_jpeg: bytes) -> None:
        """帧回调：转换 JPEG → ndarray 并入队（丢弃溢出帧）"""
        if not self._detectors:
            return
        try:
            self._queue.put_nowait(frame_jpeg)
        except asyncio.QueueFull:
            pass  # 队列满时丢帧，避免积压

    async def start(self, detection_configs: List[dict]) -> None:
        self._detection_configs = detection_configs
        self._load_detectors()
        self._task = asyncio.create_task(
            self._run_loop(),
            name=f"detector-{self.camera_id}",
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for det in self._detectors:
            det.release()
        self._detectors.clear()

    def _load_detectors(self) -> None:
        import json
        from app.detectors.yolo_detector import YoloDetector
        from app.detectors.opencv_detector import IntrusionDetector, CollisionDetector

        self._detectors.clear()
        for cfg in self._detection_configs:
            if not cfg.get("enabled"):
                continue
            config = json.loads(cfg.get("config_json", "{}"))
            dtype = cfg.get("type", "")
            if dtype == "yolo":
                det = YoloDetector(config)
            elif dtype == "intrusion":
                det = IntrusionDetector(config)
            elif dtype == "collision":
                det = CollisionDetector(config)
            else:
                continue
            # 存入 type 信息供报警服务使用
            det._detection_type = dtype
            det._detection_config_id = cfg.get("id")
            # 从 config_json 读取检测间隔（秒），默认 1 秒
            det._detect_interval = float(config.get("detect_interval", 1.0))
            self._detectors.append(det)

    async def _run_loop(self) -> None:
        import cv2
        import time
        from app.services.alert_service import alert_service

        last_alert_ts: Dict[str, float] = {}
        last_detect_ts: Dict[int, float] = {}  # detector_id -> last detect time

        while True:
            try:
                frame_jpeg = await self._queue.get()
                # JPEG → numpy BGR
                arr = np.frombuffer(frame_jpeg, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue

                for detector in self._detectors:
                    if not detector._initialized:
                        try:
                            detector.initialize()
                        except Exception as e:
                            logger.error(f"Detector init failed: {e}")
                            continue

                    # detect_interval 限频：每 N 秒最多检测一次
                    det_id = id(detector)
                    now = time.time()
                    interval = getattr(detector, '_detect_interval', 1.0)
                    if now - last_detect_ts.get(det_id, 0) < interval:
                        continue
                    last_detect_ts[det_id] = now

                    try:
                        detections = detector.detect(frame)
                    except Exception as e:
                        logger.warning(f"Detection error: {e}")
                        continue

                    if not detections:
                        continue

                    import time
                    cooldown_key = f"{self.camera_id}_{detector._detection_type}"
                    now = time.time()
                    if now - last_alert_ts.get(cooldown_key, 0) < settings.ALERT_COOLDOWN:
                        continue
                    last_alert_ts[cooldown_key] = now

                    # 绘制检测框并保存截图
                    annotated = detector.draw(frame, detections)
                    _, jpeg_buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    snapshot_bytes = jpeg_buf.tobytes()

                    top_det = max(detections, key=lambda d: d.confidence)
                    await alert_service.create(
                        camera_id=self.camera_id,
                        alert_type=detector._detection_type,
                        label=top_det.label,
                        confidence=top_det.confidence,
                        snapshot_bytes=snapshot_bytes,
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Detection worker {self.camera_id} loop error: {e}")
                await asyncio.sleep(1)


class DetectionManager:
    """全局检测调度管理器"""

    def __init__(self):
        self._workers: Dict[int, DetectionWorker] = {}

    async def start_camera(self, camera_id: int) -> None:
        """为指定摄像头启动检测工作者"""
        from app.database import AsyncSessionLocal
        from app.models.detection import DetectionConfig
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DetectionConfig).where(
                    DetectionConfig.camera_id == camera_id,
                    DetectionConfig.enabled == True,
                )
            )
            configs = result.scalars().all()

        if not configs:
            return

        cfg_dicts = [
            {"id": c.id, "type": c.type, "enabled": c.enabled, "config_json": c.config_json}
            for c in configs
        ]

        await self.stop_camera(camera_id)
        worker = DetectionWorker(camera_id)
        self._workers[camera_id] = worker
        await worker.start(cfg_dicts)

        # 订阅摄像头帧
        from app.services.camera_service import camera_manager
        state = camera_manager.get_state(camera_id)
        if state:
            state.add_frame_callback(worker.push_frame)

        logger.info(f"Detection started for camera {camera_id} ({len(cfg_dicts)} detectors)")

    async def stop_camera(self, camera_id: int) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker:
            # 取消订阅
            from app.services.camera_service import camera_manager
            state = camera_manager.get_state(camera_id)
            if state:
                state.remove_frame_callback(worker.push_frame)
            await worker.stop()

    async def reload_camera(self, camera_id: int) -> None:
        """检测配置更新后重新加载"""
        await self.stop_camera(camera_id)
        await self.start_camera(camera_id)

    async def start_all_enabled(self) -> None:
        """启动所有有检测配置的摄像头"""
        from app.database import AsyncSessionLocal
        from app.models.detection import DetectionConfig
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DetectionConfig.camera_id).where(
                    DetectionConfig.enabled == True
                ).distinct()
            )
            camera_ids = [r[0] for r in result.all()]

        for cid in camera_ids:
            await self.start_camera(cid)


detection_manager = DetectionManager()
