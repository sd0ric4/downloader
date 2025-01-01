from enum import Enum
from .base import BaseProtocolHandler
from .sync import SingleThreadedProtocolHandler
from .threaded import ThreadedProtocolHandler
from .nonblocking import NonblockingProtocolHandler
from .async_io import AsyncProtocolHandler
from .context import TransferContext
from .errors import (
    ProtocolError,
    VersionMismatchError,
    InvalidStateError,
    ChecksumError,
)


class IOMode(Enum):
    THREADED = 1  # 多线程模式
    SINGLE = 2  # 单线程阻塞模式
    NONBLOCKING = 3  # select/poll模式
    ASYNC = 4  # asyncio模式


def create_protocol_handler(mode: IOMode, **kwargs) -> BaseProtocolHandler:
    """工厂函数: 根据IO模式创建对应的处理器实例"""
    handlers = {
        IOMode.THREADED: ThreadedProtocolHandler,
        IOMode.SINGLE: SingleThreadedProtocolHandler,
        IOMode.NONBLOCKING: NonblockingProtocolHandler,
        IOMode.ASYNC: AsyncProtocolHandler,
    }

    handler_class = handlers.get(mode)
    if not handler_class:
        raise ValueError(f"Unsupported IO mode: {mode}")

    return handler_class(**kwargs)


__all__ = [
    "IOMode",
    "BaseProtocolHandler",
    "SingleThreadedProtocolHandler",
    "ThreadedProtocolHandler",
    "NonblockingProtocolHandler",
    "AsyncProtocolHandler",
    "TransferContext",
    "create_protocol_handler",
    "ProtocolError",
    "VersionMismatchError",
    "InvalidStateError",
    "ChecksumError",
]
