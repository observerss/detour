#!/usr/bin/env python
# -*- coding: utf-8 -*-
from ast import Add
import zmq
import random
import asyncio
from zmq.asyncio import Context
from typing import cast


from ..schema import RelayMethod, RelayRequest, RelayResponse, RelayData
from ..relay import deobfs, obfs, pack, unpack_response, unpack_data
from ..logger import logger
from ..config import get_config


from .socks5 import AddrType, Address, handle_socks, Socks5Request


ctx = Context.instance()
zmqconn = ctx.socket(zmq.REQ)
lock = asyncio.Lock()

CLOSE_MSG = pack(obfs(RelayData(method=RelayMethod.CLOSE, data=b"close")))


async def run_client():
    conf = get_config()

    # zmq client
    for zmq_server in conf["client_connects"]:
        logger.info(f"Connecting to {zmq_server}")
        zmqconn.connect(zmq_server)

    # local server
    assert conf["client_listen"].startswith("tcp://")
    client_ip, client_port = conf["client_listen"][6:].split(":")
    conn = await asyncio.start_server(handle_local, client_ip, int(client_port))

    listen_addr = ", ".join(str(sock.getsockname()) for sock in conn.sockets)
    logger.info(f"Start listening on {listen_addr}")

    async with conn:
        await conn.serve_forever()


async def handle_local(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    conn = ctx.socket(zmq.PAIR)
    connection = ""

    async def bind(req: Socks5Request) -> Address:
        nonlocal connection, conn

        zmqreq = RelayRequest(method=RelayMethod.CONNECT, addr=req.addr, port=req.port)
        async with lock:
            await zmqconn.send_multipart(pack(obfs(zmqreq)))
            resp = await zmqconn.recv_multipart()

        resp = cast(RelayResponse, deobfs(unpack_response(resp)))

        if resp.ok:
            connection = resp.connection
            conn.connect(resp.connection)
            logger.debug(f"[{resp.connection}] connected")
        else:
            raise RuntimeError(resp.msg)

        return Address(type=AddrType.IPv4, addr=resp.addr, port=resp.port)

    ok = await handle_socks(reader, writer, bind)
    if ok:
        asyncio.create_task(forward_reader(connection, conn, reader))
        asyncio.create_task(forward_writer(connection, conn, writer))


async def forward_reader(
    connection: str,
    conn: zmq.Socket,
    reader: asyncio.StreamReader,
    minsize: int = get_config()["min_receive_length"],
    maxsize: int = get_config()["max_receive_length"],
):
    while True:
        try:
            data = await reader.read(random.randint(minsize, maxsize))
        except ConnectionResetError:
            break
        except Exception as e:
            msg = f"[{connection}] unexpected error from local: {str(e)}"
            logger.exception(msg)
            break

        if not data:
            logger.debug(f"[{connection}] empty response from local")
            await conn.send_multipart(CLOSE_MSG)
            break

        # logger.debug(f"[{connection}] local => remote: {len(data)}, {data[:100]}")

        resp = RelayData(data=data)
        await conn.send_multipart(pack(obfs(resp)))

    logger.debug(f"[{connection}] closed reader with remote")


async def forward_writer(
    connection: str,
    conn: zmq.Socket,
    writer: asyncio.StreamWriter,
):
    while True:
        try:
            data = await conn.recv_multipart()
        except Exception as e:
            msg = f"[{connection}] unexpected error from remote: {str(e)}"
            logger.exception(msg)
            break

        resp = deobfs(unpack_data(data))
        if resp.method == RelayMethod.CLOSE:
            await conn.send_multipart(CLOSE_MSG)
            break

        # logger.debug(
        #     f"[{connection}] remote => local: {len(resp.data)}, {resp.data[:100]}"
        # )
        writer.write(resp.data)

        try:
            await writer.drain()
        except ConnectionResetError:
            break

    writer.close()
    logger.debug(f"[{connection}] closed writer with local")


def main():
    import os

    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_client())


if __name__ == "__main__":
    main()
