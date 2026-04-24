from datetime import datetime
from sqlalchemy import String, Boolean, Integer, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DetectionConfig(Base):
    __tablename__ = "detection_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    camera_id: Mapped[int] = mapped_column(Integer, ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # type: yolo | intrusion | collision
    type: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON config per type:
    #   yolo:      {"confidence": 0.5, "classes": ["person","car"], "iou": 0.45}
    #   intrusion: {"roi": [[x,y],...], "min_area": 500}
    #   collision: {"lines": [[[x1,y1],[x2,y2]],...], "direction": "any"}
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "name": self.name,
            "type": self.type,
            "enabled": self.enabled,
            "config": json.loads(self.config_json or "{}"),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
