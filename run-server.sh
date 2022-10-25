#!/bin/bash
docker rm -f detour-server
docker run --name detour-server --restart=always \
    -dit --network host \
    -e DETOUR_SERVER_LISTEN=tcp://0.0.0.0:3171 \
    detour python -m detour.server
docker logs -f detour-server
