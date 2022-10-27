#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ShadowSocks Server
"""
import struct
import socket
import asyncio
from dataclasses import dataclass, field
from typing import Coroutine, Callable, Any, List
from xml.dom.expatbuilder import parseString

from shadowsocks import cryptor

from detour.config import get_config

from .socks5 import Socks5Request, AddrType, Address, CMD
from ..logger import logger


DOWN_STREAM_BUF_SIZE = 32 * 1024


async def handle_shadow(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    bind: Callable[[Socks5Request], Coroutine[Any, Any, Address]],
) -> bool:
    peername = writer.get_extra_info("peername")
    sockname = writer.get_extra_info("sockname")
    listen = f"tcp://{sockname[0]}:{sockname[1]}"
    peer = f"tcp://{peername[0]}:{peername[1]}"

    address_type = ord(await reader.read(1))
    if address_type == AddrType.IPv4:
        address = socket.inet_ntoa(await reader.read(4))
    elif address_type == AddrType.IPv6:
        address = socket.inet_ntop(socket.AF_INET6, await reader.read(16))
    elif address_type == AddrType.DOMAIN:
        domain_length = ord(await reader.read(1))
        address = await reader.read(domain_length)
        address = address.decode()
    else:
        # shadowsocks don't reply on failure
        return False

    port = struct.unpack("!H", await reader.read(2))[0]

    req = Socks5Request(cmd=CMD.CONNECT, addr=address, port=port)

    logger.debug(f"[{listen}] shadowsocks recv <=== {peer}: {req}")

    try:
        await bind(req)
    except Exception as e:
        logger.exception(str(e))
        return False
    else:
        # it's time to start forwarding (in caller function)
        return True


@dataclass
class IOBuffer:
    data: List[bytes] = field(default_factory=list)
    idx: int = 0
    offset: int = 0
    buflen: int = 0

    def has_more(self) -> bool:
        return self.buflen > 0

    def get(self, n: int = -1) -> bytes:
        if n == -1:
            n = self.buflen

        bufs = []

        # localize
        offset = self.offset
        idx = self.idx
        buflen = self.buflen
        data = self.data
        lendata = len(data)

        while idx < lendata:
            chunk = memoryview(data[idx])
            size = len(chunk) - offset
            if size >= n:
                bufs.append(chunk[offset : offset + n])
                offset += n
                buflen -= n
                break

            # move to next chunk
            idx += 1
            bufs.append(chunk[offset:])
            offset = 0
            n -= size
            buflen -= size

        # clean up
        if idx > 10:
            self.data = data[idx:]
            idx = 0

        # unlocalize
        self.idx = idx
        self.offset = offset
        self.buflen = buflen

        return b"".join(bufs)

    def append_data(self, data: bytes):
        self.data.append(data)
        self.buflen += len(data)


def wrap_cryptor(cipher, reader, writer):
    cipher = cryptor.Cryptor("yb160101", "chacha20-ietf-poly1305")
    old_read = reader.read
    old_write = writer.write
    reader_buffer = IOBuffer()

    async def new_read(n: int = -1) -> bytes:
        if not reader_buffer.has_more():
            data = await old_read(DOWN_STREAM_BUF_SIZE)
            print("new real read", len(data), data[:100])
            # print(data)
            try:
                data = cipher.decrypt(data)
            except:
                logger.error("decrypt failed")
                parseString
            reader_buffer.append_data(data)
        data = reader_buffer.get(n)
        print("new read", n, data[:100])
        return data

    def new_write(data: bytes):
        data = cipher.encrypt(data)
        print("new write", len(data), data[:100])
        old_write(data)

    reader.read = new_read
    writer.write = new_write
    return reader, writer
