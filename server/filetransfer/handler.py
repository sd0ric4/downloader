from abc import ABC, abstractmethod
import asyncio
from enum import Enum
import logging
import queue
import threading
import select
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
from filetransfer.socket_wrapper import ProtocolSocket


class IOMode(Enum):
    THREADED = 1  # 多线程模式
    SINGLE = 2  # 单线程阻塞模式
    NONBLOCKING = 3  # select/poll模式
    ASYNC = 4  # asyncio模式


class BaseProtocolHandler(ABC):
    """协议处理器基类"""

    def __init__(self):
        self.state = ProtocolState.INIT
        self.handlers: Dict[MessageType, Callable] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.protocol_version = ProtocolVersion.V1
        self.magic = PROTOCOL_MAGIC

    def register_handler(self, msg_type: MessageType, handler: Callable) -> None:
        """
        注册消息类型对应的处理函数

        Args:
            msg_type: 消息类型
            handler: 处理函数

        Raises:
            ValueError: 当消息类型已注册时
            TypeError: 当处理函数签名不正确时
        """
        # 验证处理函数签名
        import inspect

        sig = inspect.signature(handler)
        params = list(sig.parameters.values())
        if len(params) != 2:
            raise TypeError(
                "Handler must accept exactly 2 parameters (header, payload)"
            )

        # 检查重复注册
        if msg_type in self.handlers:
            raise ValueError(
                f"Handler for message type {msg_type} is already registered"
            )

        self.handlers[msg_type] = handler

    def handle_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """处理收到的消息的基础流程"""
        if header.magic != self.magic:
            self.logger.error("Invalid magic number")
            return

        if header.version != self.protocol_version:
            self.logger.error("Protocol version mismatch")
            return

        if not self.verify_checksum(header, payload):
            self.logger.error("Checksum verification failed")
            return

        # 状态检查 - 除了握手消息外,其他消息都需要在合适的状态
        if header.msg_type != MessageType.HANDSHAKE:
            valid_states = [ProtocolState.CONNECTED, ProtocolState.TRANSFERRING]
            if self.state not in valid_states:
                self.logger.error(
                    f"Invalid state {self.state} for message type {header.msg_type}"
                )
                return

        # 无论状态如何，都调用 dispatch_message 以便设置响应
        self._dispatch_message(header, payload)

    def check_state(
        self, expected_state: ProtocolState, raise_error: bool = False
    ) -> bool:
        """
        检查当前状态是否符合预期

        Args:
            expected_state: 预期的状态
            raise_error: 如果为True且状态不匹配则抛出异常

        Returns:
            bool: 状态是否匹配

        Raises:
            ValueError: 当raise_error为True且状态不匹配时
        """
        is_valid = self.state == expected_state
        if not is_valid and raise_error:
            raise ValueError(
                f"Invalid state: expected {expected_state}, but got {self.state}"
            )
        return is_valid

    def verify_checksum(self, header: ProtocolHeader, payload: bytes) -> bool:
        """验证校验和"""
        expected = header.checksum
        actual = header.calculate_checksum(payload)
        return expected == actual

    @abstractmethod
    def _dispatch_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """分发消息到具体的处理函数"""
        pass


class ThreadedProtocolHandler(BaseProtocolHandler):
    """多线程模式处理器"""

    def __init__(self, max_workers: int = 4):
        super().__init__()
        self.max_workers = max_workers
        self.task_queue = queue.Queue()
        self.workers = []
        self._start_workers()

    def _start_workers(self):
        """启动工作线程"""
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop)
            worker.daemon = True
            worker.start()
            self.workers.append(worker)

    def _worker_loop(self):
        """工作线程主循环"""
        while True:
            try:
                task = self.task_queue.get()
                if task is None:
                    break
                header, payload = task
                self._process_message(header, payload)
                self.task_queue.task_done()
            except Exception as e:
                self.logger.error(f"Worker error: {e}")

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """将消息放入队列进行处理"""
        self.task_queue.put((header, payload))

    def _process_message(self, header: ProtocolHeader, payload: bytes):
        """具体的消息处理逻辑"""
        if not self.verify_checksum(header, payload):
            self.logger.error("Checksum verification failed")
            return

        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def shutdown(self):
        """关闭处理器"""
        for _ in self.workers:
            self.task_queue.put(None)
        for worker in self.workers:
            worker.join()


class AsyncProtocolHandler(BaseProtocolHandler):
    """异步模式处理器"""

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__()
        self.loop = loop or asyncio.get_event_loop()
        self.tasks = set()

    async def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """异步分发消息到具体的处理函数"""

        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                task = self.loop.create_task(handler(header, payload))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    async def shutdown(self):
        """关闭处理器"""
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


class NonblockingProtocolHandler(BaseProtocolHandler):
    """非阻塞模式处理器"""

    def __init__(self):
        super().__init__()
        self.socket_map = {}  # 存储socket和对应的处理状态
        self.poller = select.poll()

    def add_socket(self, sock: ProtocolSocket):
        """添加要监听的socket"""
        self.socket_map[sock.fileno()] = {"socket": sock, "state": ProtocolState.INIT}
        self.poller.register(sock, select.POLLIN)

    def remove_socket(self, sock: ProtocolSocket):
        """移除socket"""
        self.poller.unregister(sock)
        del self.socket_map[sock.fileno()]

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """分发消息到具体的处理函数"""

        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def poll(self, timeout: int = 1000):
        """轮询socket事件"""
        events = self.poller.poll(timeout)
        for fd, event in events:
            sock_info = self.socket_map.get(fd)
            if not sock_info:
                continue

            sock = sock_info["socket"]
            if event & select.POLLIN:
                try:
                    header, payload = sock.receive_message()
                    self.handle_message(header, payload)
                except Exception as e:
                    self.logger.error(f"Socket error: {e}")
                    self.remove_socket(sock)


class SingleThreadedProtocolHandler(BaseProtocolHandler):
    """单线程模式处理器"""

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """同步分发消息到具体的处理函数"""

        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")


def create_protocol_handler(mode: IOMode, **kwargs) -> BaseProtocolHandler:
    """
    工厂函数: 根据IO模式创建对应的处理器实例

    Args:
        mode: IO模式
        **kwargs: 额外的初始化参数

    Returns:
        BaseProtocolHandler的具体实现类实例
    """
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
