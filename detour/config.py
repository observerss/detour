#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
from .schema import Config


TOKEN_TRANSLATE = b"\xcd7\x9b\xb6\xadX\x16/^\xe2\x80\x9c\xaf\xa4\xc4\xc16\x054\x06\xebZ\xce\xc9\xe1\x99Q\xee\xb5#\xd9F\x0e`;\xc6W\x17C\xc3Dd(\x04\xa0\xbf\xdd\x14\xf3\xa8_1OL\xda\xber\x93\xe95\x82A\xa1\xfb\x87\xd8Uc\xf2\r\xe6\xab%\x1dR\xeaN\xed\xb1z\xb9:\xb4\x0c\x95f\xff\xfcY\x7f\x1e\xbaT\x02\x96q.-\x1b\x8a\x12\xa9\xcb\x18\x01H\xe5\x8f\x15\xef\x8c\xa5\xb39\th\xa3=\\t\xa6\xe0\xd0\x00\xc5\xb8\x94+s\xc7\n&\x98@\xbb\xe7\x03\x1a\xb0\xa7l\xdfxg\xfa\xf5\xde\x9a}\xac\xc80\xd3\xcc\x8e\xc2\xb7>PM\xbc|\xf7w']\xd6\x97\xdc\x92\xf9\x1c\x0b\x91\x882\xdbV~\xc0\x9fpi\"\x07*\x08\x90B?\x86\x83\xd7o\x0f\xf0\xf4\xd13\xb2b\xa2 S\xe8[\xcfJ\xaej\xbd\xaa\xd28\xe3\xf1{)\x19\xfe\xca<\xd4\x84!\x8bIv\x10\x9eG\x1f\x85\x13\x9da\x81nm\xec\xe4$K\x89eu\xfdk\xf8\xd5\x11E\x8d\xf6,y"
DEFAULT_TOKEN = "LzHAxq0KtWM"
SERVER_LISTEN = "tcp://0.0.0.0:3171"
CLIENT_CONNECTS = "tcp://127.0.0.1:3171"
CLIENT_LISTEN = "tcp://127.0.0.1:3170"
LOGGING_LEVEL = "DEBUG"


def get_config() -> Config:
    conf = Config()
    conf["in_docker"] = os.environ.get("DETOUR_IN_DOCKER")
    conf["token"] = os.environ.get("DETOUR_TOKEN", DEFAULT_TOKEN)

    conf["server_listen"] = os.environ.get("DETOUR_SERVER_LISTEN", SERVER_LISTEN)
    conf["server_min_port"] = 3172
    conf["server_max_port"] = 4172

    conf["client_connects"] = [
        server.strip()
        for server in os.environ.get("DETOUR_CLIENT_CONNECTS", CLIENT_CONNECTS).split(
            ","
        )
    ]
    conf["client_listen"] = os.environ.get("DETOUR_CLIENT_LISTEN", CLIENT_LISTEN)
    conf["client_username"] = os.environ.get("DETOUR_CLIENT_USERNAME", None)
    conf["client_password"] = os.environ.get("DETOUR_CLIENT_PASSWORD", None)

    conf["swaps_add_length"] = 16
    conf["min_padding_length"] = 320
    conf["max_padding_length"] = 648
    conf["min_receive_length"] = 1024
    conf["max_receive_length"] = 4096

    conf["logging_level"] = LOGGING_LEVEL

    return conf
