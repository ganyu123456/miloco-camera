FROM python:3.12-slim

LABEL maintainer="dairoot"

ENV LANG=C.UTF-8 TZ=Asia/Shanghai
ENV PIP_NO_CACHE_DIR=1
ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple
ENV PIP_TRUSTED_HOST=mirrors.tencent.com

WORKDIR /app

RUN sed -i "s@http://deb.debian.org@https://mirrors.163.com@g" /etc/apt/sources.list.d/debian.sources

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libxcb1 \
    iputils-ping && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /app/data && \
    if [ -f data/auth_info.json ]; then \
        cp data/auth_info.json /app/data/auth_info.json; \
    fi

# 强制安装 headless 版，确保无 GUI 依赖（纯流媒体网关不需要桌面渲染）
RUN pip install -U pip && pip install -e . && \
    pip install --force-reinstall opencv-python-headless

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
