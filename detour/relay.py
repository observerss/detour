#!/usr/bin/env python
# -*- coding: utf-8 -*-
import random
import secrets
from typing import Iterable, List

from .logger import logger
from .schema import RelayMessage, RelayRequest, RelayResponse, RelayData, Config
from .config import get_config, TOKEN_TRANSLATE


def make_swaps(n: int = 1000) -> List[bytes]:
    swaps_list = []
    conf = get_config()
    for _ in range(n):
        swaps = secrets.token_bytes(conf["swaps_add_length"])
        swaps = b"aeiou" + conf["token"].encode() + swaps
        swaps = b"".join((x.to_bytes(1, "little") for x in set(swaps)))
        swaps_list.append(swaps)
    return swaps_list


ALL_SWAPS = make_swaps()


def obfs(payload: RelayMessage, conf: Config = get_config()) -> RelayMessage:
    data = payload.data

    if data:
        payload.swaps = random.choice(ALL_SWAPS)
        table = get_translate_table(payload.swaps)
        if len(data) < conf["min_padding_length"]:
            pad = secrets.token_bytes(
                random.randint(conf["min_padding_length"], conf["max_padding_length"])
                - len(data)
            )
            payload.padding = len(pad)
            data = pad + data
        payload.data_obfs = encrypt(data, table)

    return payload


def deobfs(payload: RelayMessage) -> RelayMessage:
    data = payload.data_obfs
    if data:
        table = bytes.maketrans(b"", b"")
        padding = getattr(payload, "padding", 0)
        if padding:
            data = data[padding:]
        swaps = payload.swaps
        if swaps:
            table = get_translate_table(swaps)
        payload.data = decrypt(data, table)
    return payload


def pack(payload: RelayMessage) -> Iterable:
    return payload.to_array()


def unpack_request(msg: Iterable) -> RelayRequest:
    return RelayRequest.from_array(*msg)


def unpack_response(msg: Iterable) -> RelayResponse:
    return RelayResponse.from_array(*msg)


def unpack_data(msg: Iterable) -> RelayData:
    return RelayData.from_array(*msg)


def get_translate_table(swaps: bytes):
    return bytes.maketrans(swaps, swaps[::-1])


def decrypt(encrypted: bytes, table: bytes) -> bytes:
    return encrypted.translate(table)


def encrypt(raw: bytes, table: bytes) -> bytes:
    return raw.translate(table)
