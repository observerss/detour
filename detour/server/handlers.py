#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import random
import asyncio
from typing import Dict

import zmq
from zmq.asyncio import Context

from ..config import get_config
from ..logger import logger
from ..schema import RelayData, RelayRequest, RelayResponse, RelayMethod
from ..relay import obfs, deobfs, pack, unpack_data
from ..utils import logs_error

CONNECTIONS: Dict[
    str,
    tuple[
        zmq.Socket,
        asyncio.StreamReader,
        asyncio.StreamWriter,
        asyncio.Task,
        asyncio.Task,
    ],
] = {}
UP_STREAM_BUF_SIZE = 16 * 1024
LAST_ACTIVITY_TIMES: Dict[str, float] = {}


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
        conn.setsockopt(zmq.LINGER, 0)
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
        # spawn forwarders
        taskr = asyncio.create_task(forward_reader(connection, conn, reader))
        taskw = asyncio.create_task(forward_writer(connection, conn, writer))

        imalive(connection)

        CONNECTIONS[connection] = (conn, reader, writer, taskr, taskw)

        logger.debug(f"[{connection}] open connection ({addr}, {req.port})")

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


@logs_error
async def forward_reader(
    connection: str,
    conn: zmq.Socket,
    reader: asyncio.StreamReader,
    minsize: int = get_config()["min_receive_length"],
    maxsize: int = get_config()["max_receive_length"],
):
    while True:
        try:
            # DO NOT CHANGE IT, it's a shadowsocks hack
            data = await reader.read(UP_STREAM_BUF_SIZE)
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

            part = data[offset : offset + size]
            offset += size

            # logger.debug(
            #     f"[{connection}] remote => local: {len(part)}, eos={offset >= total}, {part[:100]}"
            # )

            resp = RelayData(data=part, eos=offset >= total)
            try:
                await conn.send_multipart(pack(obfs(resp)))
            except zmq.error.ZMQError:
                logger.exception(f"[{connection}] zmq already closed (reader)")
                await close_connection(connection)
                logger.debug(f"[{connection}] closed reader with remote")
                return

        if not data:
            logger.debug(f"[{connection}] empty response from remote")
            break

        imalive(connection)

    logger.debug(f"[{connection}] closed reader with remote")
    await close_connection(connection)


@logs_error
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

            # logger.debug(
            #     f"[{connection}] local => remote: {len(resp.data)}, eos={resp.eos}, {resp.data[:100]}"
            # )

            # data are splited in server
            parts.append(resp.data)
            if resp.eos:
                break

        data = b"".join(parts)
        writer.write(data)

        # do not add drain
        # it will slow down the program
        # await writer.drain()

        imalive(connection)

    await close_connection(connection)
    try:
        await writer.drain()
    except:
        pass
    logger.debug(f"[{connection}] closed writer with local")
    writer.close()


async def close_connection(connection: str):
    try:
        (conn, _, writer, taskr, taskw) = CONNECTIONS.pop(connection)
    except KeyError:
        logger.warning(f"connection {connection} is already closed!")
    else:
        taskr.cancel()
        taskw.cancel()
        writer.close()
        conn.close()


def imalive(connection: str):
    LAST_ACTIVITY_TIMES[connection] = time.time()


@logs_error
async def house_keeper(housekeep_interval=10, keep_alive=60):
    while True:
        await asyncio.sleep(housekeep_interval)
        logger.debug("house keeping...")
        to_close = []
        for connection in CONNECTIONS:
            if time.time() - LAST_ACTIVITY_TIMES.get(connection, 0) > keep_alive:
                to_close.append(connection)
                LAST_ACTIVITY_TIMES.pop(connection, None)
        for connection in to_close:
            await close_connection(connection)

        logger.debug(f"house keeped, removed {len(to_close)} stale connections")


HANDLERS = {
    RelayMethod.CONNECT: handle_connect,
    RelayMethod.CLOSE: handle_close,
}
