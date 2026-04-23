import asyncio

import cv2
import pyaudio
from av.packet import Packet
from av.video.codeccontext import VideoCodecContext

from miloco_sdk import XiaomiClient
from miloco_sdk.cli.utils import get_auth_info, print_device_list
from miloco_sdk.utils.types import MIoTCameraVideoQuality

# 全局变量用于视频解码和显示
video_decoder = None
window_name = "小米摄像头 - 视频+音频"

# 音频播放
audio_player = None
audio_stream = None


async def on_raw_video(did: str, data: bytes, ts: int, seq: int, channel: int):
    global video_decoder

    if video_decoder is None:
        video_decoder = VideoCodecContext.create("hevc", "r")
        print("✅ 已创建 HEVC 视频解码器")

    pkt = Packet(data)
    frames = video_decoder.decode(pkt)

    for frame in frames:
        bgr_frame = frame.to_ndarray(format="bgr24")
        cv2.imshow(window_name, bgr_frame)
        cv2.waitKey(1)


async def on_decode_pcm(did: str, data: bytes, ts: int, channel: int):
    """音频回调 - PCM 格式 (16-bit, mono, 16kHz)"""
    global audio_player, audio_stream
    
    if audio_player is None:
        audio_player = pyaudio.PyAudio()
        audio_stream = audio_player.open(
            format=pyaudio.paInt16,  # 16-bit
            channels=1,              # 单声道
            rate=16000,              # 16kHz
            output=True,
            frames_per_buffer=512    # 减小缓冲区，降低延迟
        )
        print("✅ 已启用音频播放（低延迟模式）")
    
    # 非阻塞方式播放音频
    if audio_stream:
        try:
            audio_stream.write(data, exception_on_underflow=False)
        except:
            pass


async def run():
    global audio_player, audio_stream
    
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
        return
    
    print(f"\n✅ 已选择设备: {device_info.get('name', '未知')}")
    print(f"   设备ID: {device_info.get('did', '未知')}")
    print(f"   型号: {device_info.get('model', '未知')}")
    print("\n🎥 正在启动视频流（带音频）...\n")

    try:
        # 启动流 - 同时注册视频和音频回调
        await client.miot_camera_stream.run_stream(
            device_info["did"], 
            0, 
            on_raw_video_callback=on_raw_video,
            on_decode_pcm_callback=on_decode_pcm,  # 启用音频
            video_quality=MIoTCameraVideoQuality.HIGH
        )
        await client.miot_camera_stream.wait_for_data()
    except KeyboardInterrupt:
        print("\n\n正在停止...")
    finally:
        # 清理音频资源
        if audio_stream:
            audio_stream.stop_stream()
            audio_stream.close()
        if audio_player:
            audio_player.terminate()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(run())
