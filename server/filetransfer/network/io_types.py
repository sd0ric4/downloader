# io_types.py
from enum import Enum


class IOMode(Enum):
    THREADED = 1  # 多线程模式
    SINGLE = 2  # 单线程阻塞模式
    NONBLOCKING = 3  # select/poll模式
    ASYNC = 4  # asyncio模式
