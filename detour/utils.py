#!/usr/bin/env python
# -*- coding utf-8 -*-
import inspect
import functools
from .logger import logger


def logs_error(func):
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def inner(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"{func.__name__} throws err: {str(e)}")

        return inner
    else:

        @functools.wraps(func)
        def inner(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(f"{func.__name__} throws err: {str(e)}")

        return inner
