#!/bin/bash
VER=`python -c "import detour;print(detour.version)"`
docker build -t detour:"$VER" .
docker build -t detour:lastest .
mkdir -p dist
docker save -o dist/detour-latest.tar detour:lastest
