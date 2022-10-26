#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import logging
import logging.config

from .config import get_config

conf = get_config()
LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
logging.config.dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "level": conf["logging_level"],
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file.server": {
                "level": conf["logging_level"],
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "when": "midnight",
                "filename": os.path.join(LOGS_DIR, "running.server.log"),
                "backupCount": 5,
            },
            "file.client": {
                "level": conf["logging_level"],
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "when": "midnight",
                "filename": os.path.join(LOGS_DIR, "running.client.log"),
                "backupCount": 5,
            },
            "file": {
                "level": conf["logging_level"],
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "when": "midnight",
                "filename": os.path.join(LOGS_DIR, "running.default.log"),
                "backupCount": 5,
            },
        },
        "loggers": {
            "server": {
                "level": conf["logging_level"],
                "handlers": ["console", "file.server"],
            },
            "client": {
                "level": conf["logging_level"],
                "handlers": ["console", "file.client"],
            },
            "default": {
                "level": conf["logging_level"],
                "handlers": ["console", "file"],
            },
        },
        "disable_existing_loggers": True,
    }
)

logger = logging.getLogger(os.environ.get("DETOUR_CMD", "default"))
