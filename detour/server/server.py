#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import zmq
import socket
import urllib.request
import asyncio
from zmq.asyncio import Context
from typing import List, cast

from detour.utils import logs_error

from ..schema import RelayMessage, RelayMethod, RelayRequest, RelayResponse
from ..relay import deobfs, obfs, pack, unpack_request
from ..logger import logger
from ..config import SERVER_LISTEN, get_config
from .handlers import HANDLERS, house_keeper


async def run_server():
    conf = get_config()
    ctx = Context.instance()
    conn = ctx.socket(zmq.ROUTER)
    conn.setsockopt(zmq.LINGER, 0)
    connection = conf["server_listen"]
    conn.bind(connection)

    # determinte listen
    listen = connection[6:].split(":")
    got_listen = False
    if conf["in_docker"]:
        with urllib.request.urlopen("http://ipecho.net/plain") as response:
            listen[0] = response.read().decode()
        got_listen = True

    logger.info(f"start listening on {connection}")
    asyncio.create_task(house_keeper())

    while True:
        logger.debug(f"[{connection}] waiting for request")
        if got_listen:
            msg = await conn.recv_multipart()
        else:
            msg, listen = await get_msg_and_listen(conn, listen)
            got_listen = True

        # msg[0] is zmq identity
        msgid, msg = msg[0], msg[1:]
        try:
            req = cast(RelayRequest, deobfs(unpack_request(msg)))
            req.connection = f"tcp://{listen[0]}:{listen[1]}"
        except Exception as e:
            msg = f"Bad Request"
            logger.exception(msg)
            resp = RelayResponse(
                method=RelayMethod.CONNECT, ok=False, msg=msg, data=b"random stuff"
            )
            msg_back = pack(obfs(resp))
            await conn.send_multipart([msgid] + msg_back)
        else:
            asyncio.create_task(handle_request(conn, req, msgid))


@logs_error
async def handle_request(conn: zmq.Socket, req: RelayRequest, msgid: bytes):
    try:
        resp = await HANDLERS[req.method](req)
    except Exception as e:
        msg = f"unhandled error: {str(e)}"
        logger.exception(msg)
        resp = RelayResponse(method=req.method, ok=False, msg=msg, data=b"random stuff")
    msg_back = pack(obfs(resp))
    await conn.send_multipart([msgid] + msg_back)


async def get_msg_and_listen(conn: zmq.Socket, listen: str):
    msg = cast(List[zmq.Frame], await conn.recv_multipart(copy=False))

    fileno = msg[1].get(zmq.SRCFD)
    try:
        fileno2 = os.dup(fileno)
    except OSError:
        if listen[0] == "0.0.0.0":
            msg = "on windows, server ip should not be 0.0.0.0"
            logger.error(msg)
            resp = RelayResponse(
                method=RelayMethod.CONNECT,
                ok=False,
                msg=msg,
                data=b"random stuff",
            )
            msg_back = pack(obfs(resp))
            await conn.send_multipart(msg_back)
            sys.exit(1)
    else:
        listen = socket.socket(fileno=fileno2).getsockname()
    msg = [m.bytes for m in msg]
    return msg, listen


def main():
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
