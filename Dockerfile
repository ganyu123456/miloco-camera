FROM python:3.12-slim

LABEL maintainer="dairoot"

ENV LANG=C.UTF-8 TZ=Asia/Shanghai
ENV PIP_NO_CACHE_DIR=1
ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple
ENV PIP_TRUSTED_HOST=mirrors.tencent.com

WORKDIR /app

# 切换国内 apt 镜像
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

# 复制认证文件到镜像（如果本地 data/auth_info.json 存在则打包进去）
RUN mkdir -p /app/data && \
    if [ -f data/auth_info.json ]; then \
        cp data/auth_info.json /app/data/auth_info.json; \
    fi

# ultralytics 会拉入 opencv-python（完整版），需在其之后强制换回 headless 版
RUN pip install -U pip && pip install -e . && \
    pip install --force-reinstall opencv-python-headless

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
