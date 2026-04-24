from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    did: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    local_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channel: Mapped[int] = mapped_column(Integer, default=0)
    video_quality: Mapped[str] = mapped_column(String(10), default="HIGH")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "did": self.did,
            "model": self.model,
            "local_ip": self.local_ip,
            "enabled": self.enabled,
            "channel": self.channel,
            "video_quality": self.video_quality,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
