#!/usr/bin/env python
# -*- coding: utf-8 -*-
from sre_parse import parse_template
import zmq
import random
import asyncio
import logging
import functools
from zmq.asyncio import Context
from typing import Any, Callable, Coroutine, cast

from shadowsocks import cryptor

from ..schema import RelayMethod, RelayRequest, RelayResponse, RelayData
from ..relay import deobfs, obfs, pack, unpack_response, unpack_data
from ..logger import logger
from ..config import get_config


from .socks5 import AddrType, Address, negotiate_socks, Socks5Request
from .shadow import negotiate_shadow, wrap_cryptor


CLOSE_MSG = pack(obfs(RelayData(method=RelayMethod.CLOSE, data=b"close")))


async def run_client():
    conf = get_config()

    # local servers
    servers = []

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
        cipher = cryptor.Cryptor(
            get_config()["client_shadow_password"], get_config()["client_shadow_method"]
        )

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        conn_shadow = await asyncio.start_server(
            functools.partial(handle_local, negotiate_shadow, cipher),
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
            raise RuntimeError(resp.msg)

        return Address(type=AddrType.IPv4, addr=resp.addr, port=resp.port)

    if cipher:
        reader, writer = wrap_cryptor(cipher, reader, writer)

    # ok = await handle_socks(reader, writer, bind)
    ok = await negotiate(reader, writer, bind)
    if ok:
        asyncio.create_task(forward_reader(connection, sconn, reader))
        asyncio.create_task(forward_writer(connection, sconn, writer))
    else:
        # byebye client
        writer.write(b"")
        await writer.drain()
        writer.close()


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
            data = await reader.read(32768)
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

            print(">>>>>>>>>>>>", offset, total, size)
            part = data[offset : offset + size]
            offset += size

            logger.debug(
                f"[{connection}] local => remote: {len(part)}, eos={offset >= total}, {part[:100]}"
            )

            resp = RelayData(data=part, eos=offset >= total)
            await conn.send_multipart(pack(obfs(resp)))

        if not data:
            logger.debug(f"[{connection}] empty response from local")
            await conn.send_multipart(CLOSE_MSG)
            break

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

                logger.debug(
                    f"[{connection}] remote => local: {len(resp.data)}, eos={resp.eos}, {resp.data[:100]}"
                )
                # data are splited in server
                parts.append(resp.data)
                if resp.eos:
                    break

        # we MUST do a single write here, because shadowsocks assumes a whole packet
        data = b"".join(parts)
        print("write", len(data), data[:100])
        writer.write(data)

        try:
            await writer.drain()
        except ConnectionResetError:
            logger.error("reset!!!!")
            break

    conn.close()
    writer.close()
    logger.debug(f"[{connection}] closed writer with local")


def main():
    import os

    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run_client())


if __name__ == "__main__":
    main()
