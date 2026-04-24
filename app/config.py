import os
import sys
from pathlib import Path


def _get_data_dir() -> Path:
    """
    用户持久化数据目录（DB / 截图等）。
    · PyInstaller --onefile：放在 .exe 同级目录的 data/ 下，程序重启后数据不丢失。
    · 普通运行：项目根目录的 data/ 下。
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "data"
    return Path(__file__).parent.parent / "data"


DATA_DIR = _get_data_dir()
PICTURES_DIR = DATA_DIR / "pictures"

DATA_DIR.mkdir(exist_ok=True)
PICTURES_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8080"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    DB_URL: str = f"sqlite+aiosqlite:///{DATA_DIR / 'gateway.db'}"

    # Paths
    DATA_DIR: Path = DATA_DIR
    PICTURES_DIR: Path = PICTURES_DIR
    AUTH_INFO_PATH: Path = DATA_DIR / "auth_info.json"

    # SMTP (QQ Mail)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.qq.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")  # QQ mail authorization code
    SMTP_TO: str = os.getenv("SMTP_TO", "")
    SMTP_ENABLED: bool = os.getenv("SMTP_ENABLED", "false").lower() == "true"

    # MediaMTX
    MEDIAMTX_BIN: str = os.getenv("MEDIAMTX_BIN", "mediamtx")
    RTSP_PORT: int = int(os.getenv("RTSP_PORT", "8554"))
    RTSP_HOST: str = os.getenv("RTSP_HOST", "localhost")

    # Detection defaults
    YOLO_MODEL: str = os.getenv("YOLO_MODEL", "yolo11n.pt")
    YOLO_CONFIDENCE: float = float(os.getenv("YOLO_CONFIDENCE", "0.5"))

    # Frame queue size per camera
    FRAME_QUEUE_SIZE: int = int(os.getenv("FRAME_QUEUE_SIZE", "2"))

    # Alert cooldown (seconds) - avoid alert flood for same camera+type
    ALERT_COOLDOWN: int = int(os.getenv("ALERT_COOLDOWN", "10"))


settings = Settings()
