#!/usr/bin/env python
# -*- coding: utf-8 -*-
import enum
import orjson
from typing import TypedDict, List
from dataclasses import dataclass


class RelayMethod(str, enum.Enum):
    CONNECT = "CONNECT"
    DATA = "DATA"
    CLOSE = "CLOSE"


class Config(TypedDict):
    logging_level: str
    token: str  # encrypt token
    swaps_add_length: int
    min_padding_length: int
    max_padding_length: int
    min_receive_length: int
    max_receive_length: int
    server_listen: str
    server_min_port: int
    server_max_port: int
    client_connects: List[str]
    client_listen: str
    client_username: str
    client_password: str


@dataclass
class RelayRequest:
    method: str  # CONNECT/CLOSE
    addr: str = None  # remote addr, only valid in CONNECT
    port: int = None  # remote port, only valid in CONNECT
    padding: int = 0  # padding length
    connection: str = ""  # connection to close, only valid in CLOSE
    swaps: bytes = b""  # swaps length must be even
    data: bytes = b""  # data to send
    data_obfs: bytes = b""

    @classmethod
    def from_array(cls, arr: bytes, swaps: bytes, data_obfs: bytes) -> "RelayRequest":
        req = RelayRequest(*orjson.loads(arr))
        req.swaps = swaps
        req.data_obfs = data_obfs
        return req

    def to_array(self):
        return [
            orjson.dumps(
                [self.method, self.addr, self.port, self.padding, self.connection]
            ),
            self.swaps,
            self.data_obfs,
        ]


@dataclass
class RelayResponse:
    method: str  # CONNECT/CLOSE
    ok: bool = False  # ok or not
    msg: str = "undefined"  # failure message if appliable
    addr: str = None  # remote addr, only valid in CONNECT
    port: int = None  # remote port, only valid in CONNECT
    padding: int = 0  # padding length
    connection: str = ""
    swaps: bytes = b""  # swaps length must be even
    data: bytes = b""  # response data, only valid in DATA
    data_obfs: bytes = b""

    @classmethod
    def from_array(cls, arr: bytes, swaps: bytes, data_obfs: bytes) -> "RelayResponse":
        resp = RelayResponse(*orjson.loads(arr))
        resp.swaps = swaps
        resp.data_obfs = data_obfs
        return resp

    def to_array(self):
        return [
            orjson.dumps(
                [
                    self.method,
                    self.ok,
                    self.msg,
                    self.addr,
                    self.port,
                    self.padding,
                    self.connection,
                ]
            ),
            self.swaps,
            self.data_obfs,
        ]


@dataclass
class RelayData:
    method: str = RelayMethod.DATA  # DATA/CLOSE
    padding: int = 0  # padding length
    swaps: bytes = b""  # swaps length must be even
    data: bytes = b""  # response data, only valid in DATA
    data_obfs: bytes = b""

    @classmethod
    def from_array(cls, arr: bytes, swaps: bytes, data_obfs: bytes) -> "RelayData":
        resp = RelayData(*orjson.loads(arr))
        resp.swaps = swaps
        resp.data_obfs = data_obfs
        return resp

    def to_array(self):
        return [
            orjson.dumps(
                [
                    self.method,
                    self.padding,
                ]
            ),
            self.swaps,
            self.data_obfs,
        ]


RelayMessage = RelayRequest | RelayResponse | RelayData
