"""
Web 视频流服务 - 通过浏览器访问小米摄像头
在摄像头所在网络的电脑上运行此脚本，然后通过浏览器访问
"""
import asyncio
import io
from datetime import datetime

from flask import Flask, Response, render_template_string
from av.packet import Packet
from av.video.codeccontext import VideoCodecContext
import cv2

from miloco_sdk import XiaomiClient
from miloco_sdk.cli.utils import get_auth_info
from miloco_sdk.utils.types import MIoTCameraVideoQuality

# Flask 应用
app = Flask(__name__)

# 全局变量
video_decoder = None
latest_frame = None
camera_info_global = None


def _create_video_decoder():
    """自动选择最优解码器：优先 NVIDIA GPU，回退到 CPU"""
    import subprocess
    import av

    def try_codec(name):
        try:
            av.Codec(name, "r")
            return True
        except Exception:
            return False

    try:
        result = subprocess.run(
            ["ffmpeg", "-hwaccels"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        hw_list = [x.strip() for x in result.stdout.strip().split("\n")[1:] if x.strip()]
    except FileNotFoundError:
        hw_list = []

    # 优先 NVIDIA CUVID 硬解
    if ("cuda" in hw_list or "cuvid" in hw_list) and try_codec("hevc_cuvid"):
        print("✅ 已创建 HEVC 解码器 [NVIDIA GPU - hevc_cuvid]")
        return VideoCodecContext.create("hevc_cuvid", "r")

    # 次选 V4L2 硬解（ARM 设备）
    if try_codec("hevc_v4l2m2m"):
        print("✅ 已创建 HEVC 解码器 [V4L2 硬件加速]")
        return VideoCodecContext.create("hevc_v4l2m2m", "r")

    # 回退 CPU 软解
    print("✅ 已创建 HEVC 解码器 [CPU 软解码]")
    return VideoCodecContext.create("hevc", "r")


async def on_raw_video(did: str, data: bytes, ts: int, seq: int, channel: int):
    """视频回调函数"""
    global video_decoder, latest_frame

    if video_decoder is None:
        video_decoder = _create_video_decoder()

    try:
        pkt = Packet(data)
        frames = video_decoder.decode(pkt)

        for frame in frames:
            bgr_frame = frame.to_ndarray(format="bgr24")
            ret, jpeg = cv2.imencode('.jpg', bgr_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ret:
                latest_frame = jpeg.tobytes()
    except Exception as e:
        print(f"解码错误: {e}")


def generate_frames():
    """生成视频流（Motion JPEG）"""
    global latest_frame
    
    while True:
        if latest_frame is not None:
            # 以 multipart/x-mixed-replace 格式发送
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + latest_frame + b'\r\n')
        else:
            # 如果还没有帧，稍作等待
            import time
            time.sleep(0.1)


@app.route('/')
def index():
    """主页 - 显示视频流"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>小米摄像头 Web 流</title>
        <meta charset="utf-8">
        <style>
            body {
                margin: 0;
                padding: 20px;
                background-color: #1a1a1a;
                color: #ffffff;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
            }
            h1 {
                margin-bottom: 10px;
            }
            .info {
                background-color: #2a2a2a;
                padding: 15px 30px;
                border-radius: 8px;
                margin-bottom: 20px;
                text-align: center;
            }
            .camera-name {
                font-size: 24px;
                margin-bottom: 5px;
            }
            .camera-id {
                color: #888;
                font-size: 14px;
            }
            .video-container {
                max-width: 100%;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            }
            img {
                display: block;
                max-width: 100%;
                height: auto;
            }
            .status {
                margin-top: 20px;
                padding: 10px 20px;
                background-color: #2ecc71;
                border-radius: 6px;
                font-weight: bold;
            }
            .timestamp {
                margin-top: 10px;
                color: #888;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <h1>📹 小米摄像头实时监控</h1>
        <div class="info">
            <div class="camera-name">{{ camera_name }}</div>
            <div class="camera-id">设备 ID: {{ camera_id }}</div>
        </div>
        <div class="video-container">
            <img src="{{ url_for('video_feed') }}" alt="摄像头视频流">
        </div>
        <div class="status">● 在线</div>
        <div class="timestamp">
            页面加载时间: <span id="time"></span>
        </div>
        <script>
            // 显示当前时间
            document.getElementById('time').textContent = new Date().toLocaleString('zh-CN');
            
            // 每秒更新时间戳
            setInterval(() => {
                document.getElementById('time').textContent = new Date().toLocaleString('zh-CN');
            }, 1000);
        </script>
    </body>
    </html>
    """
    camera_name = camera_info_global.get('name', '未知设备') if camera_info_global else '加载中...'
    camera_id = camera_info_global.get('did', '---') if camera_info_global else '---'
    
    return render_template_string(html, camera_name=camera_name, camera_id=camera_id)


@app.route('/video_feed')
def video_feed():
    """视频流路由"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


async def start_camera_stream():
    """启动摄像头流"""
    global camera_info_global
    
    client = XiaomiClient()
    auth_info = get_auth_info(client)
    client.set_access_token(auth_info["access_token"])

    device_list = client.home.get_device_list()
    online_devices = [d for d in device_list if d.get("isOnline", False)]

    if not online_devices:
        print("\n❌ 没有在线设备")
        return

    # 只选择 Xiaomi Smart Camera 3 (设备 ID: 1153134874)
    target_did = "1153134874"
    device_info = None
    
    for device in online_devices:
        if device.get('did') == target_did:
            device_info = device
            break
    
    if not device_info:
        print(f"\n❌ 未找到设备 ID 为 {target_did} 的摄像头")
        print(f"可用设备列表:")
        for dev in online_devices:
            print(f"  - {dev.get('name')} (ID: {dev.get('did')})")
        return
    
    camera_info_global = device_info
    
    print(f"\n✅ 已选择设备: {device_info.get('name', '未知')}")
    print(f"   设备ID: {device_info.get('did', '未知')}")
    print(f"   型号: {device_info.get('model', '未知')}")
    print(f"   IP: {device_info.get('localip', '未知')}")
    print("\n🎥 正在启动视频流（高清）...")

    # 启动流
    await client.miot_camera_stream.run_stream(
        device_info["did"],
        0,
        on_raw_video_callback=on_raw_video,
        video_quality=MIoTCameraVideoQuality.HIGH
    )
    
    print("✅ 视频流已启动")
    print("\n" + "="*60)
    print("📱 Web 服务已启动！")
    print("="*60)
    print("\n访问地址:")
    print(f"  本地访问: http://localhost:8888")
    print(f"  局域网访问: http://<本机IP>:8888")
    print(f"  同局域网访问: 在浏览器打开上面的地址即可")
    print("\n在浏览器中打开上述任意地址即可查看视频流")
    print("按 Ctrl+C 停止服务\n")
    print("="*60 + "\n")

    await client.miot_camera_stream.wait_for_data()


def run_flask():
    """运行 Flask 服务器"""
    app.run(host='0.0.0.0', port=8888, threaded=True, debug=False)


if __name__ == "__main__":
    import threading
    
    # 在后台线程启动 Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # 等待 Flask 启动
    import time
    time.sleep(2)
    
    # 在主线程启动摄像头流
    try:
        asyncio.run(start_camera_stream())
    except KeyboardInterrupt:
        print("\n\n⚠️  正在停止服务...")
        print("✅ 服务已停止")
