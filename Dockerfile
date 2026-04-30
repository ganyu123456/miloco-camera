FROM python:3.12-slim

LABEL maintainer="dairoot"

ENV LANG=C.UTF-8 TZ=Asia/Shanghai
ENV PIP_NO_CACHE_DIR=1
ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple
ENV PIP_TRUSTED_HOST=mirrors.tencent.com

# MediaMTX 版本，升级时只改这里
# v1.12.0+ 支持 H.265/HEVC WebRTC（WHEP），浏览器可直接播放小米摄像头原始流，零转码
ARG MEDIAMTX_VERSION=v1.12.0

WORKDIR /app

RUN sed -i "s@http://deb.debian.org@https://mirrors.163.com@g" /etc/apt/sources.list.d/debian.sources

# 安装系统依赖：运行时库 + ffmpeg + 下载工具
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libxcb1 \
    iputils-ping \
    ffmpeg \
    wget \
    ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 MediaMTX（RTSP 服务器，支持 amd64 / arm64）
RUN ARCH=$(dpkg --print-architecture) && \
    case "${ARCH}" in \
      amd64)   MTX_ARCH="amd64" ;; \
      arm64)   MTX_ARCH="arm64v8" ;; \
      armhf)   MTX_ARCH="armv7" ;; \
      *)       MTX_ARCH="amd64" ;; \
    esac && \
    wget -q -O /tmp/mediamtx.tar.gz \
      "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${MTX_ARCH}.tar.gz" && \
    tar -xzf /tmp/mediamtx.tar.gz -C /usr/local/bin mediamtx && \
    chmod +x /usr/local/bin/mediamtx && \
    rm /tmp/mediamtx.tar.gz && \
    mediamtx --version

COPY . .

RUN mkdir -p /app/data && \
    if [ -f data/auth_info.json ]; then \
        cp data/auth_info.json /app/data/auth_info.json; \
    fi

# 强制安装 headless 版，确保无 GUI 依赖
RUN pip install -U pip && pip install -e . && \
    pip install --force-reinstall opencv-python-headless

# 8080 = Web UI / MJPEG API
# 8554 = RTSP 推流端口（MediaMTX 默认，使用 host 网络时宿主机直接可访问）
# 8889 = WebRTC WHEP 端口（浏览器通过 WHEP 协议直接拉 H.265 流，零转码）
EXPOSE 8080 8554 8889

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
