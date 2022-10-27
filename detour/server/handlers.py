#!/usr/bin/env python
# -*- coding: utf-8 -*-
from fileinput import close
import random
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
        reader, writer = await asyncio.open_connection(req.addr, req.port)
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

        logger.debug(f"[{connection}] open connection ({req.addr}, {req.port})")

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
            data = await reader.read(random.randint(minsize, maxsize))
        except ConnectionResetError:
            break
        except Exception as e:
            msg = f"[{connection}] unexpected error from remote: {str(e)}"
            logger.exception(msg)
            break

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
    while True:
        try:
            msg = await conn.recv_multipart()
        except Exception as e:
            msg = f"[{connection}] unexpected error from local: {str(e)}"
            logger.exception(msg)
            break

        resp = deobfs(unpack_data(msg))
        # logger.debug(
        #     f"[{connection}] local => remote: {len(resp.data)}, {resp.data[:100]}"
        # )
        if resp.method == RelayMethod.CLOSE:
            break

        writer.write(resp.data)

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

            asyncio.create_task(close_later(1))
        except zmq.error.ZMQError:
            pass


HANDLERS = {
    RelayMethod.CONNECT: handle_connect,
    RelayMethod.CLOSE: handle_close,
}
