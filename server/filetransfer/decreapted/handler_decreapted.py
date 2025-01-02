from abc import ABC, abstractmethod
import asyncio
from enum import Enum
import logging
import queue
import socket
import threading
import select
from typing import Optional, Dict, Any, Callable, Set
from dataclasses import dataclass

from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
from filetransfer.network import ProtocolSocket


class IOMode(Enum):
    THREADED = 1  # 多线程模式
    SINGLE = 2  # 单线程阻塞模式
    NONBLOCKING = 3  # select/poll模式
    ASYNC = 4  # asyncio模式


class ProtocolError(Exception):
    """协议相关错误的基类"""

    pass


class VersionMismatchError(ProtocolError):
    """版本不匹配错误"""

    pass


class InvalidStateError(ProtocolError):
    """状态错误"""

    pass


class ChecksumError(ProtocolError):
    """校验和错误"""

    pass


@dataclass
class TransferContext:
    """传输上下文"""

    filename: str
    total_chunks: int
    current_chunk: int = 0
    file_size: int = 0
    checksum: Optional[int] = None


class BaseProtocolHandler(ABC):
    """增强的协议处理器基类"""

    def __init__(self):
        self.state = ProtocolState.INIT
        self.handlers: Dict[MessageType, Callable] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.protocol_version = ProtocolVersion.V1
        self.magic = PROTOCOL_MAGIC
        self.supported_versions: Set[ProtocolVersion] = {ProtocolVersion.V1}
        self._error_handlers: Dict[type, Callable] = {}
        self.session_id: Optional[int] = None
        self.sequence_number: int = 0
        self.transfer_context: Optional[TransferContext] = None

    def register_handler(self, msg_type: MessageType, handler: Callable) -> None:
        """注册消息处理器"""
        self._validate_handler_signature(handler)
        if msg_type in self.handlers:
            raise ValueError(
                f"Handler for message type {msg_type} is already registered"
            )
        self.handlers[msg_type] = handler

    def handle_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """处理收到的消息"""
        try:
            # 1. 基础验证
            if header.magic != self.magic:
                self.logger.error("Invalid magic number")
                return

            if header.version not in self.supported_versions:
                self.logger.error("Protocol version mismatch")
                return

            if not self.verify_checksum(header, payload):
                self.logger.error("Checksum verification failed")
                return

            # 2. 状态检查和消息处理
            # 特殊处理：ERROR 和 LIST_ERROR 消息
            if header.msg_type in {MessageType.ERROR, MessageType.LIST_ERROR}:
                self.state = ProtocolState.ERROR
                self._dispatch_message(header, payload)
                return

            # 特殊处理：HANDSHAKE 消息
            if header.msg_type == MessageType.HANDSHAKE:
                self._dispatch_message(header, payload)
                return

            # ACK 消息可以在任何非 INIT 状态处理
            if header.msg_type == MessageType.ACK:
                if self.state != ProtocolState.INIT:
                    self._dispatch_message(header, payload)
                return

            # 其他消息的状态检查
            if self.state == ProtocolState.INIT:
                self.logger.error("Invalid state for non-handshake message")
                return

            # 3. 根据当前状态和消息类型处理
            can_process = False

            if self.state == ProtocolState.CONNECTED:
                # CONNECTED 状态可以处理的消息
                if header.msg_type in {
                    MessageType.HANDSHAKE,
                    MessageType.FILE_REQUEST,
                    MessageType.LIST_REQUEST,
                    MessageType.NLST_REQUEST,
                    MessageType.CLOSE,
                    MessageType.RESUME_REQUEST,
                    MessageType.LIST_RESPONSE,
                    MessageType.NLST_RESPONSE,
                }:
                    can_process = True

            elif self.state == ProtocolState.TRANSFERRING:
                # TRANSFERRING 状态可以处理的消息
                if header.msg_type in {
                    MessageType.HANDSHAKE,
                    MessageType.FILE_DATA,
                    MessageType.FILE_METADATA,
                    MessageType.CHECKSUM_VERIFY,
                    MessageType.CLOSE,
                    MessageType.LIST_RESPONSE,
                    MessageType.NLST_RESPONSE,
                }:
                    can_process = True

            if can_process:
                self._dispatch_message(header, payload)

                # 4. 更新序列号（仅在正常消息处理后）
                if header.msg_type not in {
                    MessageType.HANDSHAKE,
                    MessageType.ERROR,
                    MessageType.LIST_ERROR,
                }:
                    self.sequence_number = header.sequence_number

        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            self.state = ProtocolState.ERROR

    def _validate_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """验证消息的有效性"""
        if header.magic != self.magic:
            raise ProtocolError("Invalid magic number")

        if header.version not in self.supported_versions:
            raise VersionMismatchError("Protocol version mismatch")

        if not self.verify_checksum(header, payload):
            raise ChecksumError("Checksum verification failed")

    def check_state(
        self, expected_state: ProtocolState, raise_error: bool = False
    ) -> bool:
        """检查当前状态是否符合预期"""
        is_valid = self.state == expected_state
        if not is_valid and raise_error:
            raise ValueError(
                f"Invalid state: expected {expected_state}, but got {self.state}"
            )
        return is_valid

    def _validate_handler_signature(self, handler: Callable) -> None:
        """验证处理器函数签名"""
        import inspect

        sig = inspect.signature(handler)
        params = list(sig.parameters.values())
        if len(params) != 2:
            raise TypeError(
                "Handler must accept exactly 2 parameters (header, payload)"
            )

    @abstractmethod
    def _dispatch_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """分发消息到具体的处理函数"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭处理器，清理资源"""
        self.state = ProtocolState.COMPLETED
        self.handlers.clear()
        self._error_handlers.clear()
        self.session_id = None
        self.transfer_context = None

    def verify_checksum(self, header: ProtocolHeader, payload: bytes) -> bool:
        """验证校验和"""
        expected = header.checksum
        actual = header.calculate_checksum(payload)
        return expected == actual

    def add_supported_version(self, version: ProtocolVersion) -> None:
        """添加支持的协议版本"""
        self.supported_versions.add(version)

    def remove_supported_version(self, version: ProtocolVersion) -> None:
        """移除支持的协议版本"""
        if version in self.supported_versions:
            self.supported_versions.remove(version)


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
    """非阻塞模式处理器(使用select)"""

    def __init__(self):
        super().__init__()
        self.socket_map = {}  # 存储socket和对应的处理状态
        self.listening_sockets = set()  # 监听socket集合
        self.read_sockets = set()  # 需要监听读事件的socket集合
        self.write_sockets = set()  # 需要监听写事件的socket集合
        self.pending_connections = set()  # 等待连接完成的socket集合

    def _is_server_socket(self, sock):
        """检查是否为服务器socket"""
        if not sock.socket:
            return False

        # 检查是否为SOCK_STREAM类型且已绑定地址
        try:
            sock_type = sock.socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            if sock_type != socket.SOCK_STREAM:
                return False

            # 尝试获取socket的本地地址
            address = sock.socket.getsockname()
            if not address:
                return False

            # 尝试获取peer地址，如果能获取说明是已连接的客户端socket
            try:
                sock.socket.getpeername()
                return False
            except socket.error:
                # 不能获取peer地址，并且其他检查都通过，说明可能是监听socket
                pass

            return True

        except socket.error:
            return False

    def add_socket(self, sock: ProtocolSocket):
        """添加要监听的socket"""
        fd = sock.fileno()
        self.socket_map[fd] = {"socket": sock, "state": ProtocolState.INIT}

        # 检查是否为服务器socket
        if self._is_server_socket(sock):
            self.listening_sockets.add(fd)
            self.read_sockets.add(fd)
            self.logger.debug(f"Added server socket {fd}")
            try:
                addr = sock.socket.getsockname()
                self.logger.debug(f"Server socket {fd} bound to {addr}")
            except socket.error:
                pass
        else:
            self.read_sockets.add(fd)
            self.write_sockets.add(fd)
            self.pending_connections.add(fd)
            self.logger.debug(f"Added client socket {fd}")
            try:
                addr = sock.socket.getpeername()
                self.logger.debug(f"Client socket {fd} connected to {addr}")
            except socket.error:
                pass

    def remove_socket(self, sock: ProtocolSocket):
        """移除socket"""
        fd = sock.fileno()
        if fd in self.socket_map:
            self.logger.debug(f"Removing socket {fd}")
            self.listening_sockets.discard(fd)
            self.read_sockets.discard(fd)
            self.write_sockets.discard(fd)
            self.pending_connections.discard(fd)
            del self.socket_map[fd]

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """分发消息到具体的处理函数"""
        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
                self.logger.debug(
                    f"Message dispatched to handler: type={header.msg_type}"
                )
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def handle_events(self, timeout: float = 1.0):
        """使用select监听socket事件"""
        if not self.socket_map:
            return

        self.logger.debug(f"开始select，当前有 {len(self.socket_map)} 个socket")
        self.logger.debug(f"监听socket列表: {self.listening_sockets}")
        self.logger.debug(f"读socket列表: {self.read_sockets}")
        self.logger.debug(f"写socket列表: {self.write_sockets}")
        self.logger.debug(f"待连接socket列表: {self.pending_connections}")

        try:
            readable, writable, exceptional = select.select(
                self.read_sockets,
                self.write_sockets,
                self.read_sockets | self.write_sockets,
                timeout,
            )

            # 处理异常的socket
            for sock_fd in exceptional:
                sock_info = self.socket_map.get(sock_fd)
                if sock_info:
                    self.logger.debug(f"Socket {sock_fd} encountered an error")
                    self.remove_socket(sock_info["socket"])

            # 处理可写的socket（用于检查连接状态）
            for sock_fd in writable:
                if sock_fd in self.pending_connections:
                    sock_info = self.socket_map.get(sock_fd)
                    if sock_info and sock_info["socket"].check_connection():
                        self.pending_connections.discard(sock_fd)
                        self.write_sockets.discard(sock_fd)  # 连接完成后不再监听写事件
                        self.logger.debug(f"Client socket {sock_fd} connected")

            # 处理可读的socket
            for sock_fd in readable:
                sock_info = self.socket_map.get(sock_fd)
                if not sock_info:
                    continue

                sock = sock_info["socket"]

                # 处理监听socket上的新连接
                if sock_fd in self.listening_sockets:
                    try:
                        client_sock, addr = sock.socket.accept()
                        self.logger.debug(f"接受新连接: {addr}")
                        # 设置非阻塞模式
                        client_sock.setblocking(False)
                        # 创建新的ProtocolSocket并添加
                        client_protocol = ProtocolSocket(
                            client_sock, io_mode=IOMode.NONBLOCKING
                        )
                        self.add_socket(client_protocol)
                    except Exception as e:
                        self.logger.error(f"Accept error: {e}")
                    continue

                # 处理普通socket的数据
                try:
                    header, payload = sock.receive_message()
                    self.logger.debug(f"收到消息: type={header.msg_type}")
                    self.handle_message(header, payload)
                except ConnectionError as e:
                    self.logger.error(f"Connection error: {e}")
                    self.remove_socket(sock)
                except Exception as e:
                    self.logger.error(f"Socket error: {e}")
                    self.remove_socket(sock)

        except Exception as e:
            self.logger.error(f"Select error: {e}")


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

    def close(self) -> None:
        """实现父类的抽象方法，关闭处理器并清理资源"""
        super().close()


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
