#!/bin/bash
docker rm -f detour-client
docker run --name detour-client --restart=always \
    -dit -p3170:3170 \
    -e DETOUR_CLIENT_CONNECTS=tcp://47.244.2.82:3171 \
    -e DETOUR_CLIENT_LISTEN=tcp://0.0.0.0:3170 \
    detour python -m detour.client
docker logs -f detour-client
