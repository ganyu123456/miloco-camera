"""
小米 OAuth Token 定时刷新服务（方案 A：主动刷新）

策略：
  · 启动时读取 auth_info.json，计算 token 到期时间
  · 在到期前 TOKEN_REFRESH_ADVANCE 秒主动用 refresh_token 换新 token
  · 续签成功后逐路重启所有小米摄像头，使新 token 生效
  · 下次唤醒时间 = 新 token 到期时间 - TOKEN_REFRESH_ADVANCE
  · 若续签失败，等待 TOKEN_RETRY_INTERVAL 秒后重试，不影响已在运行的流
"""
import asyncio
import json
import logging
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 到期前多少秒主动续签（默认 12 小时）
TOKEN_REFRESH_ADVANCE = 12 * 3600
# 续签失败后重试间隔（默认 30 分钟）
TOKEN_RETRY_INTERVAL = 30 * 60


def _read_auth_info() -> dict:
    auth_file = Path(settings.AUTH_INFO_PATH)
    if not auth_file.exists():
        return {}
    with open(auth_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _seconds_until_refresh(auth_info: dict) -> float:
    """返回距离下次需要续签还有多少秒（负值代表已需立即续签）。"""
    created_at = auth_info.get("created_at", 0)
    expires_in = auth_info.get("expires_in", 0)
    refresh_at = created_at + expires_in - TOKEN_REFRESH_ADVANCE
    return refresh_at - time.time()


async def _do_refresh(auth_info: dict) -> dict | None:
    """
    用 refresh_token 换新 token，写入文件，返回新的 auth_info。
    失败时返回 None。
    """
    loop = asyncio.get_running_loop()

    def _sync_refresh():
        from miloco_sdk import XiaomiClient
        client = XiaomiClient()
        refresh_token = auth_info.get("refresh_token")
        if not refresh_token:
            return None
        try:
            result = client.authorize.refresh_access_token_from_mico(refresh_token)
            new_auth = result.get("result") or result
            if not new_auth or not new_auth.get("access_token"):
                return None
            new_auth["created_at"] = int(time.time())
            auth_file = Path(settings.AUTH_INFO_PATH)
            with open(auth_file, "w", encoding="utf-8") as f:
                json.dump(new_auth, f, ensure_ascii=True, indent=2)
            return new_auth
        except Exception as e:
            logger.warning(f"TokenService: refresh_token 续签失败: {e}")
            return None

    return await loop.run_in_executor(None, _sync_refresh)


async def token_refresh_loop() -> None:
    """
    后台永久运行的 token 刷新协程，在 lifespan 里以 asyncio.Task 启动。
    """
    logger.info("TokenService: 后台 Token 刷新服务已启动")

    while True:
        auth_info = _read_auth_info()
        if not auth_info:
            logger.warning("TokenService: 未找到 auth_info.json，60 秒后重试")
            await asyncio.sleep(60)
            continue

        wait_secs = _seconds_until_refresh(auth_info)
        expire_ts = auth_info.get("created_at", 0) + auth_info.get("expires_in", 0)

        if wait_secs > 0:
            import datetime
            refresh_time = datetime.datetime.fromtimestamp(
                expire_ts - TOKEN_REFRESH_ADVANCE
            ).strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                f"TokenService: Token 有效，将在 {refresh_time} "
                f"（{wait_secs/3600:.1f} 小时后）主动续签"
            )
            await asyncio.sleep(wait_secs)

        # 到达续签窗口，执行续签
        logger.info("TokenService: 开始主动续签 access_token ...")
        new_auth = await _do_refresh(auth_info)

        if new_auth:
            logger.info("TokenService: ✅ access_token 续签成功，正在重启所有小米摄像头以使新 token 生效")
            await _restart_xiaomi_cameras()
            # 续签成功，继续下一轮循环（重新计算下次续签时间）
        else:
            logger.warning(
                f"TokenService: ❌ 续签失败，{TOKEN_RETRY_INTERVAL//60} 分钟后重试"
            )
            await asyncio.sleep(TOKEN_RETRY_INTERVAL)


async def _restart_xiaomi_cameras() -> None:
    """停止并重启所有小米品牌摄像头，使新 token 在重连时生效。"""
    from app.services.camera_service import camera_manager

    xiaomi_ids = [
        s.camera_id
        for s in camera_manager.all_states()
        if s.brand == "xiaomi"
    ]

    if not xiaomi_ids:
        logger.info("TokenService: 无小米摄像头需要重启")
        return

    logger.info(f"TokenService: 重启 {len(xiaomi_ids)} 路小米摄像头: {xiaomi_ids}")

    for camera_id in xiaomi_ids:
        try:
            await camera_manager.stop(camera_id)
            # 短暂等待，避免同时重连触发小米云限流
            await asyncio.sleep(2)
            await camera_manager.start(camera_id)
            logger.info(f"TokenService: 摄像头 {camera_id} 重启完成")
        except Exception as e:
            logger.error(f"TokenService: 摄像头 {camera_id} 重启失败: {e}")
