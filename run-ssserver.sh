#!/bin/bash
docker rm -f ssserver-rust
docker run --name ssserver-rust \
  --network host \
  --restart always \
  -e http_proxy=socks5://127.0.0.1:3170 \
  -e https_proxy=socks5://127.0.0.1:3170 \
  -v `pwd`/config.json:/etc/shadowsocks-rust/config.json \
  -dit ghcr.io/shadowsocks/ssserver-rust:latest
docker logs -f ssserver-rust
