FROM python:3.10-slim

ENV DETOUR_TOKEN=Tr3QVNuLRJc
ENV DETOUR_SERVER_LISTEN=tcp://0.0.0.0:3171
ENV DETOUR_CLIENT_CONNECTS=tcp://127.0.0.1:3171
ENV DETOUR_CLIENT_LISTEN_SOCKS5=tcp://0.0.0.0:3170
ENV DETOUR_CLIENT_LISTEN_SHADOW=tcp://0.0.0.0:3169
ENV DETOUR_IN_DOCKER=yes

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i 's/archive.ubuntu.com/mirrors.ustc.edu.cn/g' /etc/apt/sources.list \
    && apt -y update && apt -y install --no-install-recommends libsodium-dev tzdata

ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai

WORKDIR /app
RUN mkdir -p logs

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


COPY shadowsocks shadowsocks
COPY detour detour

EXPOSE 3169-3171

CMD ["python", "-m", "detour.client"]