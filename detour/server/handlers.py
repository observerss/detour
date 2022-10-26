#!/usr/bin/env python
# -*- coding: utf-8 -*-
from fileinput import close
import random
import socket
import asyncio
from typing import Dict

import zmq
from zmq.asyncio import Context

from ..config import get_config
from ..logger import logger
from ..schema import RelayData, RelayRequest, RelayResponse, RelayMethod
from ..relay import obfs, deobfs, pack, unpack_data

CONNECTIONS: Dict[
    str, tuple[zmq.Socket, asyncio.StreamReader, asyncio.StreamWriter]
] = {}


async def handle_connect(req: RelayRequest) -> RelayResponse:
    resp = RelayResponse(method=req.method)
    try:
        addr = req.addr
        # dns first
        # try:
        #     int(req.addr.split(".")[0])
        #     addr = req.addr
        # except:
        #     res = await asyncio.get_running_loop().getaddrinfo(
        #         req.addr, req.port, proto=socket.IPPROTO_TCP
        #     )
        #     addr = res[0][-1][0]

        reader, writer = await asyncio.open_connection(addr, req.port)
    except Exception as e:
        resp.ok = False
        msg = f"open ({req.addr}, {req.port}) failed: {str(e)}"
        resp.msg = msg
        logger.exception(resp.msg)
    else:
        conf = get_config()
        ctx = Context.instance()
        conn = ctx.socket(zmq.PAIR)
        assert req.connection.startswith(
            "tcp://"
        ), "connection should startswith tcp://"
        server_ip, port = req.connection[6:].split(":")
        port = conn.bind_to_random_port(
            addr=f"tcp://0.0.0.0",
            min_port=conf["server_min_port"],
            max_port=conf["server_max_port"],
        )

        connection = f"tcp://{server_ip}:{port}"
        CONNECTIONS[connection] = (conn, reader, writer)

        logger.debug(f"[{connection}] open connection ({addr}, {req.port})")

        # spawn forwarders
        asyncio.create_task(forward_reader(connection, conn, reader))
        asyncio.create_task(forward_writer(connection, conn, writer))

        # make response body
        resp.ok = True
        resp.connection = connection
        resp.data = b"random stuff"
        addr, port = writer.get_extra_info("sockname")
        resp.addr = addr
        resp.port = port
    return resp


async def handle_close(req: RelayRequest) -> RelayResponse:
    resp = RelayResponse(method=req.method, ok=True, data=b"random stuff")

    await close_connection(req.connection)
    return resp


async def forward_reader(
    connection: str,
    conn: zmq.Socket,
    reader: asyncio.StreamReader,
    minsize: int = get_config()["min_receive_length"],
    maxsize: int = get_config()["max_receive_length"],
):
    while True:
        try:
            # DO NOT CHANGE 16384, it's a shadowsocks hack
            data = await reader.read(16384)
        except ConnectionResetError:
            break
        except Exception as e:
            msg = f"[{connection}] unexpected error from remote: {str(e)}"
            logger.exception(msg)
            break

        # split data into small packages
        offset = 0
        total = len(data)
        while offset < total:
            size = random.randint(minsize, maxsize)

            print(">>>>>>>>>>>>", offset, total, size)
            part = data[offset : offset + size]
            offset += size

            logger.debug(
                f"[{connection}] remote => local: {len(part)}, eos={offset >= total}, {part[:100]}"
            )

            resp = RelayData(data=part, eos=offset >= total)
            try:
                await conn.send_multipart(pack(obfs(resp)))
            except zmq.error.ZMQError:
                logger.exception(f"[{connection}] zmq already closed (reader)")
                await close_connection(connection)
                logger.debug(f"[{connection}] closed reader with remote")
                return

        # logger.debug(f"[{connection}] remote => local: {len(data)}, {data[:100]}")

        resp = RelayData(data=data)
        msg = pack(obfs(resp))
        await conn.send_multipart(msg)

        if not data:
            logger.debug(f"[{connection}] empty response from remote")
            break

    await close_connection(connection)
    logger.debug(f"[{connection}] closed reader with remote")


async def forward_writer(
    connection: str,
    conn: zmq.Socket,
    writer: asyncio.StreamWriter,
):
    outer_looping = True
    while outer_looping:
        parts = []
        while True:
            try:
                data = await conn.recv_multipart()
            except Exception as e:
                msg = f"[{connection}] unexpected error from local: {str(e)}"
                logger.exception(msg)
                outer_looping = False
                continue

            resp = deobfs(unpack_data(data))
            if resp.method == RelayMethod.CLOSE:
                outer_looping = False
                continue

            logger.debug(
                f"[{connection}] local => remote: {len(resp.data)}, eos={resp.eos}, {resp.data[:100]}"
            )

            # data are splited in server
            parts.append(resp.data)
            if resp.eos:
                break

        data = b"".join(parts)
        print("write", len(data), data[:100])
        writer.write(data)

        # do not add drain
        # it will slow down the program
        # await writer.drain()

    await close_connection(connection)
    try:
        await writer.drain()
    except:
        pass
    writer.close()
    logger.debug(f"[{connection}] closed writer with local")


async def close_connection(connection: str):
    logger.debug(f"[{connection}] closing...")
    try:
        (conn, _, _) = CONNECTIONS.pop(connection)
    except KeyError:
        logger.warning(f"connection {connection} is already closed!")
    else:
        try:
            await conn.send_multipart(
                pack(obfs(RelayData(method=RelayMethod.CLOSE, data=b"close")))
            )

            async def close_later(seconds: float = 1):
                await asyncio.sleep(seconds)
                conn.close()

            asyncio.create_task(close_later(seconds=10))
        except zmq.error.ZMQError:
            logger.exception("zmq socket already closed")


HANDLERS = {
    RelayMethod.CONNECT: handle_connect,
    RelayMethod.CLOSE: handle_close,
}
