#!/bin/bash
docker rm -f detour-client
docker run --name detour-client --restart=always \
    -dit -p11900:3170 -p11899:3169 \
    -e DETOUR_CLIENT_CONNECTS=tcp://47.244.2.82:3171 \
    -e DETOUR_CLIENT_LISTEN_SOCKS5=tcp://0.0.0.0:3170 \
    -e DETOUR_CLIENT_LISTEN_SHADOW=tcp://0.0.0.0:3169 \
    detour python -m detour.client
docker logs -f detour-client