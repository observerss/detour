#!/usr/bin/env python
SERVER_IP=cbtest2.hjc.rocks
SERVER_PORT=11903
METHOD=chacha20-ietf-poly1305
PASSWORD=yb160101
LOCAL_PORT=1086

python -c "from shadowsocks.local import main; main()" -s $SERVER_IP -p $SERVER_PORT -m $METHOD -k $PASSWORD -l $LOCAL_PORT
