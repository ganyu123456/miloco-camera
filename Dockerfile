FROM python:3.12-slim

ENV LANG=C.UTF-8 TZ=Asia/Shanghai

MAINTAINER dairoot

WORKDIR /app

# 更新源
RUN sed -i "s@http://deb.debian.org@https://mirrors.163.com@g" /etc/apt/sources.list.d/debian.sources

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple
ENV PIP_TRUSTED_HOST=mirrors.tencent.com

COPY . .

# 复制认证文件到镜像（如果本地 data/auth_info.json 存在则打包进去）
RUN mkdir -p /app/data && \
    if [ -f data/auth_info.json ]; then \
        cp data/auth_info.json /app/data/auth_info.json; \
    fi

RUN pip install -U pip && pip install -e . && pip install flask opencv-python-headless

# 暴露 Web 端口
EXPOSE 8888

# 启动 Web 流服务
CMD ["python", "examples/web_stream.py"]
