import asyncio

import cv2
from av.packet import Packet
from av.video.codeccontext import VideoCodecContext

from miloco_sdk import XiaomiClient
from miloco_sdk.cli.utils import get_auth_info, print_device_list
from miloco_sdk.utils.types import MIoTCameraVideoQuality

# 全局变量用于视频解码和显示
video_decoder = None
window_name = "小米摄像头 - HEVC 视频流"


async def on_raw_video(did: str, data: bytes, ts: int, seq: int, channel: int):
    global video_decoder

    # 首次调用时创建 HEVC 解码器
    if video_decoder is None:
        video_decoder = VideoCodecContext.create("hevc", "r")
        print("已创建 HEVC 视频解码器")

    # 解码视频帧
    pkt = Packet(data)
    frames = video_decoder.decode(pkt)

    for frame in frames:
        # 转换为 BGR 格式 (OpenCV 使用 BGR)
        bgr_frame = frame.to_ndarray(format="bgr24")

        # 显示视频帧
        cv2.imshow(window_name, bgr_frame)
        cv2.waitKey(1)


async def run():
    client = XiaomiClient()
    auth_info = get_auth_info(client)
    client.set_access_token(auth_info["access_token"])

    device_list = client.home.get_device_list()
    online_devices = [d for d in device_list if d.get("isOnline", False)]

    if not online_devices:
        print("\n设备列表: 暂无在线设备")
        return

    print_device_list(online_devices)
    
    # 只选择 Xiaomi Smart Camera 3 (设备 ID: 1153134874)
    target_did = "1153134874"
    device_info = None
    
    for device in online_devices:
        if device.get('did') == target_did:
            device_info = device
            break
    
    if not device_info:
        print(f"\n❌ 未找到设备 ID 为 {target_did} 的摄像头")
        print("请检查设备是否在线或修改脚本中的 target_did")
        return
    
    print(f"\n✅ 已选择设备: {device_info.get('name', '未知')}")
    print(f"   设备ID: {device_info.get('did', '未知')}")
    print(f"   型号: {device_info.get('model', '未知')}")
    print("\n🎥 正在启动视频流，按 Ctrl+C 停止...\n")

    # 启动流
    await client.miot_camera_stream.run_stream(
        device_info["did"], 0, on_raw_video_callback=on_raw_video, video_quality=MIoTCameraVideoQuality.HIGH
    )
    await client.miot_camera_stream.wait_for_data()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(run())
