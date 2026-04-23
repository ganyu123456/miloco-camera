import asyncio
import time

import cv2
from av.packet import Packet
from av.video.codeccontext import VideoCodecContext

from miloco_sdk import XiaomiClient
from miloco_sdk.cli.utils import get_auth_info, print_device_list
from miloco_sdk.utils.types import MIoTCameraVideoQuality

# 全局变量用于视频解码和显示
video_decoder = None
window_name = "小米摄像头 - HEVC 视频流"
frame_count = 0
start_time = None
MAX_RUN_TIME = 30  # 最大运行时间（秒）


async def on_raw_video(did: str, data: bytes, ts: int, seq: int, channel: int):
    global video_decoder, frame_count, start_time

    # 首次调用时创建 HEVC 解码器和记录开始时间
    if video_decoder is None:
        video_decoder = VideoCodecContext.create("hevc", "r")
        start_time = time.time()
        print("✅ 已创建 HEVC 视频解码器")

    # 检查是否超时
    if start_time and (time.time() - start_time) > MAX_RUN_TIME:
        print(f"\n⏱️  已运行 {MAX_RUN_TIME} 秒，自动退出...")
        raise KeyboardInterrupt()

    # 解码视频帧
    pkt = Packet(data)
    frames = video_decoder.decode(pkt)

    for frame in frames:
        frame_count += 1
        if frame_count % 30 == 0:  # 每30帧打印一次
            elapsed = time.time() - start_time if start_time else 0
            print(f"✅ 已接收并解码 {frame_count} 帧视频 | 分辨率: {frame.width}x{frame.height} | 已运行: {elapsed:.1f}秒")
        
        # 转换为 BGR 格式 (OpenCV 使用 BGR)
        bgr_frame = frame.to_ndarray(format="bgr24")

        # 显示视频帧
        cv2.imshow(window_name, bgr_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):  # 按 'q' 退出
            print("\n用户按下 'q' 键，正在退出...")
            return


async def run():
    client = XiaomiClient()
    auth_info = get_auth_info(client)
    client.set_access_token(auth_info["access_token"])

    device_list = client.home.get_device_list()
    online_devices = [d for d in device_list if d.get("isOnline", False)]

    if not online_devices:
        print("\n❌ 设备列表: 暂无在线设备")
        return

    print_device_list(online_devices)
    
    # 自动选择第一个设备（序号 1）
    index = 0  # 对应序号 1
    device_info = online_devices[index]
    print(f"\n✅ 已自动选择设备: {device_info.get('name', '未知')} (序号 {index + 1})")
    print(f"   设备ID: {device_info.get('did', '未知')}")
    print(f"   IP地址: {device_info.get('localip', '未知')}")
    print(f"   型号: {device_info.get('model', '未知')}")
    print("\n🎥 正在启动视频流...")
    print("   提示: 视频窗口会自动弹出，按 'q' 键可退出\n")

    try:
        # 启动流
        await client.miot_camera_stream.run_stream(
            device_info["did"], 
            0, 
            on_raw_video_callback=on_raw_video, 
            video_quality=MIoTCameraVideoQuality.HIGH
        )
        print("✅ 视频流已启动，正在等待数据...\n")
        await client.miot_camera_stream.wait_for_data()
    except KeyboardInterrupt:
        print("\n\n⚠️  检测到 Ctrl+C，正在停止视频流...")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cv2.destroyAllWindows()
        print("\n✅ 视频流已停止")
        print(f"   总共接收 {frame_count} 帧视频")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n程序已退出")
