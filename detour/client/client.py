#!/usr/bin/env python
# -*- coding: utf-8 -*-
import zmq
import time
import random
import asyncio
import functools
from zmq.asyncio import Context
from typing import Any, Callable, Coroutine, Dict, Tuple, cast

from ..schema import RelayMethod, RelayRequest, RelayResponse, RelayData
from ..relay import deobfs, obfs, pack, unpack_response, unpack_data
from ..logger import logger
from ..config import get_config
from ..utils import logs_error


from .socks5 import AddrType, Address, negotiate_socks, Socks5Request
from .shadow import negotiate_shadow, wrap_cryptor


CLOSE_MSG = pack(obfs(RelayData(method=RelayMethod.CLOSE, data=b"close")))
DOWN_STREAM_BUF_SIZE = 32 * 1024
CONNECTIONS: Dict[
    str,
    Tuple[
        zmq.Socket,
        asyncio.StreamReader,
        asyncio.StreamWriter,
        asyncio.Task,
        asyncio.Task,
    ],
] = {}
LAST_ACTIVITY_TIMES: Dict[str, float] = {}


async def run_client():
    conf = get_config()

    # local servers
    servers = []

    asyncio.create_task(house_keeper())

    # socks5 server
    if conf.get("client_listen_socks5"):
        assert conf["client_listen_socks5"].startswith("tcp://")

        client_ip, client_port_socks5 = conf["client_listen_socks5"][6:].split(":")
        conn_socks5 = await asyncio.start_server(
            functools.partial(handle_local, negotiate_socks, None),
            client_ip,
            int(client_port_socks5),
        )
        listen_addr_socks5 = ", ".join(
            str(sock.getsockname()) for sock in conn_socks5.sockets
        )
        logger.info(f"Start listening socks5 on {listen_addr_socks5}")

        await conn_socks5.start_serving()
        servers.append(conn_socks5)

    # shadowsocks server
    if conf.get("client_listen_shadow"):
        assert conf["client_listen_shadow"].startswith("tcp://")

        client_ip, client_port_shadow = conf["client_listen_shadow"][6:].split(":")

        conn_shadow = await asyncio.start_server(
            functools.partial(handle_local, negotiate_shadow, True),
            client_ip,
            int(client_port_shadow),
        )

        listen_addr_shadow = ", ".join(
            str(sock.getsockname()) for sock in conn_shadow.sockets
        )
        logger.info(f"Start listening shadow on {listen_addr_shadow}")

        await conn_shadow.start_serving()
        servers.append(conn_shadow)

    # serve forever
    if servers:
        future = asyncio.get_running_loop().create_future()
        try:
            await future
        except asyncio.CancelledError:
            try:
                for server in servers:
                    server.close()

                for server in servers:
                    await server.wait_closed()
            finally:
                raise
    else:
        logger.error("please specify socks5/shadowsocks server to listen")


@logs_error
async def handle_local(
    negotiate: Callable[
        [
            asyncio.StreamReader,
            asyncio.StreamWriter,
            Callable[[Socks5Request], Coroutine[Any, Any, Address]],
        ],
        Coroutine[Any, Any, bool],
    ],
    cipher: Any,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
):
    """
    local server handler

    :param negotiate: a function that handles the negotiate stage of SOCKS5/ShadowSocks Protocol
    :param cipher: a class instance that has 'encrypt' and 'decrypt' method
    :param reader: a reader for the socket peer
    :param writer: a writer for the socket peer
    """
    ctx = Context.instance()
    conf = get_config()
    hconn = ctx.socket(zmq.DEALER)  # handshake conn
    sconn = ctx.socket(zmq.PAIR)  # stream conn
    hconn.setsockopt(zmq.LINGER, 0)
    sconn.setsockopt(zmq.LINGER, 0)
    connection = ""

    async def bind(req: Socks5Request) -> Address:
        nonlocal connection, sconn

        # lazy connect to server
        for zmq_server in conf["client_connects"]:
            logger.debug(f"Connecting to {zmq_server}")
            hconn.connect(zmq_server)

        zmqreq = RelayRequest(method=RelayMethod.CONNECT, addr=req.addr, port=req.port)
        await hconn.send_multipart(pack(obfs(zmqreq)))
        resp = await hconn.recv_multipart()

        resp = cast(RelayResponse, deobfs(unpack_response(resp)))

        if resp.ok:
            connection = resp.connection
            sconn.connect(resp.connection)
            logger.debug(f"[{resp.connection}] connected")
        else:
            return

        return Address(type=AddrType.IPv4, addr=resp.addr, port=resp.port)

    if cipher:
        reader, writer = wrap_cryptor(reader, writer)

    # ok = await handle_socks(reader, writer, bind)
    ok = await negotiate(reader, writer, bind)
    if ok:
        taskr = asyncio.create_task(forward_reader(connection, sconn, reader))
        taskw = asyncio.create_task(forward_writer(connection, sconn, writer))
        CONNECTIONS[connection] = (sconn, reader, writer, taskr, taskw)
        imalive(connection)
    else:
        # byebye client
        writer.write(b"")
        await writer.drain()
        writer.close()

    # avoid too many open files
    hconn.close()


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
            # DO NOT change this value
            data = await reader.read(DOWN_STREAM_BUF_SIZE)
        except ConnectionResetError:
            break
        except Exception as e:
            msg = f"[{connection}] unexpected error from local: {str(e)}"
            logger.exception(msg)
            break

        offset = 0
        total = len(data)
        while offset < total:
            size = random.randint(minsize, maxsize)

            part = data[offset : offset + size]
            offset += size

            # logger.debug(
            #     f"[{connection}] local => remote: {len(part)}, eos={offset >= total}, {part[:20]}"
            # )

            resp = RelayData(data=part, eos=offset >= total)
            await conn.send_multipart(pack(obfs(resp)))

        if not data:
            logger.debug(f"[{connection}] empty response from local")
            await conn.send_multipart(CLOSE_MSG)
            break

        imalive(connection)

    logger.debug(f"[{connection}] closed reader with remote")
    close_connection(connection)


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
                msg = f"[{connection}] unexpected error from remote: {str(e)}"
                logger.exception(msg)
                outer_looping = False
                continue
            else:
                resp = deobfs(unpack_data(data))
                if resp.method == RelayMethod.CLOSE:
                    await conn.send_multipart(CLOSE_MSG)
                    outer_looping = False
                    continue

                # logger.debug(
                #     f"[{connection}] remote => local: {len(resp.data)}, eos={resp.eos}, {resp.data[:20]}"
                # )

                # data are splited in server
                parts.append(resp.data)
                if resp.eos:
                    break

        # we MUST do a single write here, because shadowsocks assumes a whole packet
        data = b"".join(parts)
        writer.write(data)

        try:
            await writer.drain()
        except ConnectionResetError:
            break

        imalive(connection)

    logger.debug(f"[{connection}] closed writer with local")
    close_connection(connection)


def close_connection(connection: str):
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
            close_connection(connection)
        logger.debug(f"house keeped, removed {len(to_close)} stale connections")


def main():
    import os

    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_client())


if __name__ == "__main__":
    main()
