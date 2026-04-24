"""检测算法配置 API"""
import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.detection import DetectionConfig

router = APIRouter(prefix="/api/detections", tags=["detections"])


class DetectionCreate(BaseModel):
    camera_id: int
    name: str
    type: str       # yolo | intrusion | collision
    enabled: bool = False
    config: Dict[str, Any] = {}


class DetectionUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


@router.get("")
async def list_detections(camera_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    q = select(DetectionConfig)
    if camera_id is not None:
        q = q.where(DetectionConfig.camera_id == camera_id)
    result = await db.execute(q)
    items = result.scalars().all()
    return {"detections": [d.to_dict() for d in items]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_detection(body: DetectionCreate, db: AsyncSession = Depends(get_db)):
    valid_types = {"yolo", "intrusion", "collision"}
    if body.type not in valid_types:
        raise HTTPException(400, f"type must be one of {valid_types}")

    cfg = DetectionConfig(
        camera_id=body.camera_id,
        name=body.name,
        type=body.type,
        enabled=body.enabled,
        config_json=json.dumps(body.config),
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)

    if body.enabled:
        from app.services.detection_service import detection_manager
        asyncio.create_task(detection_manager.reload_camera(body.camera_id))

    return cfg.to_dict()


@router.patch("/{detection_id}")
async def update_detection(
    detection_id: int, body: DetectionUpdate, db: AsyncSession = Depends(get_db)
):
    cfg = await db.get(DetectionConfig, detection_id)
    if not cfg:
        raise HTTPException(404, "DetectionConfig not found")

    if body.name is not None:
        cfg.name = body.name
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.config is not None:
        cfg.config_json = json.dumps(body.config)

    await db.commit()
    await db.refresh(cfg)

    # 重新加载检测器
    from app.services.detection_service import detection_manager
    asyncio.create_task(detection_manager.reload_camera(cfg.camera_id))

    return cfg.to_dict()


@router.delete("/{detection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_detection(detection_id: int, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(DetectionConfig, detection_id)
    if not cfg:
        raise HTTPException(404, "DetectionConfig not found")
    camera_id = cfg.camera_id
    await db.delete(cfg)
    await db.commit()

    from app.services.detection_service import detection_manager
    asyncio.create_task(detection_manager.reload_camera(camera_id))


@router.post("/{detection_id}/toggle")
async def toggle_detection(detection_id: int, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(DetectionConfig, detection_id)
    if not cfg:
        raise HTTPException(404, "DetectionConfig not found")
    cfg.enabled = not cfg.enabled
    await db.commit()
    await db.refresh(cfg)

    from app.services.detection_service import detection_manager
    asyncio.create_task(detection_manager.reload_camera(cfg.camera_id))

    return {"id": cfg.id, "enabled": cfg.enabled}
