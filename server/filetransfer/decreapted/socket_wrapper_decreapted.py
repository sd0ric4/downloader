import socket
import logging
import select
import threading
import queue
import asyncio
from enum import Enum
from typing import Optional
from .protocol import MessageType, ProtocolHeader, ProtocolVersion, PROTOCOL_MAGIC
import zlib

logger = logging.getLogger(__name__)
HEADERSIZE = 32  # 修正：头部大小应为32字节

# io_mode 参数用于控制套接字的 I/O 模式


class IOMode(Enum):
    THREADED = 1  # 多线程模式
    SINGLE = 2  # 单线程阻塞模式
    NONBLOCKING = 3  # select/poll模式
    ASYNC = 4  # asyncio模式


class BaseSocket:
    def __init__(self, sock=None, io_mode=IOMode.SINGLE):
        self.socket = sock or socket.socket()
        self.io_mode = io_mode
        self.read_buffer = bytearray()
        self.write_buffer = bytearray()
        self.connected = False
        if io_mode == IOMode.THREADED:
            self._write_queue = queue.Queue()
            self._read_queue = queue.Queue()
            self._start_threads()
        elif io_mode == IOMode.NONBLOCKING:
            self.write_fds = set()
            self.socket.setblocking(False)

    def connect(self, addr):
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_connect for async mode")
        try:
            self.socket.connect(addr)
            self.connected = True
        except BlockingIOError:
            # 非阻塞模式下的connect会抛出BlockingIOError
            pass

    def check_connection(self):
        """检查非阻塞连接是否完成"""
        if not self.connected and self.io_mode == IOMode.NONBLOCKING:
            try:
                _, writable, _ = select.select([], [self.socket], [], 0.1)
                if self.socket in writable:
                    self.connected = True
            except (BlockingIOError, ConnectionError):
                pass
        return self.connected

    async def async_connect(self, host, port):
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")
        reader, writer = await asyncio.open_connection(host, port)
        self.socket = (reader, writer)
        self.connected = True

    def _start_threads(self):
        def reader():
            while True:
                try:
                    data = self._blocking_recv(8192)
                    if data:
                        self._read_queue.put(data)
                except:
                    pass

        def writer():
            while True:
                data = self._write_queue.get()
                try:
                    self._blocking_send(data)
                except:
                    pass

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=writer, daemon=True).start()

    def _blocking_send(self, data):
        return self.socket.send(data)

    def _blocking_recv(self, size):
        return self.socket.recv(size)

    def _nonblocking_send(self, data):
        if data:
            self.write_buffer.extend(data)
            self.write_fds.add(self.socket)

        sent = 0
        try:
            _, writable, _ = select.select([], self.write_fds, [], 0.1)
            if self.socket in writable:
                sent = self.socket.send(self.write_buffer)
                self.write_buffer = self.write_buffer[sent:]
                if not self.write_buffer:
                    self.write_fds.remove(self.socket)
        except BlockingIOError:
            pass
        return sent

    def _nonblocking_recv(self, size):
        try:
            readable, _, _ = select.select([self.socket], [], [], 0.1)
            if self.socket in readable:
                return self.socket.recv(size)
        except BlockingIOError:
            pass
        return None

    async def _async_send(self, data):
        _, writer = self.socket
        writer.write(data)
        await writer.drain()
        return len(data)

    async def _async_recv(self, size):
        reader, _ = self.socket
        return await reader.read(size)

    def _send_all(self, data: bytes) -> int:
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_send_all for async mode")
        elif self.io_mode == IOMode.THREADED:
            self._write_queue.put(data)
            return len(data)
        elif self.io_mode == IOMode.NONBLOCKING:
            sent_total = 0
            remaining = data
            while remaining:
                try:
                    _, writable, _ = select.select([], [self.socket], [], 0.1)
                    if self.socket in writable:
                        sent = self.socket.send(remaining)
                        if sent == 0:
                            raise ConnectionError("Socket connection broken")
                        sent_total += sent
                        remaining = remaining[sent:]
                except BlockingIOError:
                    continue
            return sent_total
        else:  # SINGLE mode
            sent_total = 0
            while sent_total < len(data):
                try:
                    sent = self.socket.send(data[sent_total:])
                    if sent == 0:
                        raise ConnectionError("Socket connection broken")
                    sent_total += sent
                except (BlockingIOError, InterruptedError):
                    continue
            return sent_total

    def _recv_all(self, size: int) -> Optional[bytes]:
        if not self.connected:
            raise ConnectionError("Not connected")
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_recv_all for async mode")
        elif self.io_mode == IOMode.THREADED:
            data = bytearray()
            while len(data) < size:
                chunk = self._read_queue.get()
                if not chunk:
                    raise ConnectionError("Connection closed by peer")
                data.extend(chunk)
                if len(data) > size:
                    self._read_queue.put(data[size:])
                    data = data[:size]
            return bytes(data)
        elif self.io_mode == IOMode.NONBLOCKING:
            data = bytearray()
            while len(data) < size:
                try:
                    readable, _, _ = select.select([self.socket], [], [], 0.1)
                    if self.socket in readable:
                        chunk = self.socket.recv(min(size - len(data), 8192))
                        if not chunk:
                            raise ConnectionError("Connection closed by peer")
                        data.extend(chunk)
                except BlockingIOError:
                    continue
            return bytes(data)
        else:  # SINGLE mode
            data = bytearray()
            while len(data) < size:
                try:
                    chunk = self.socket.recv(min(size - len(data), 8192))
                    if not chunk:
                        raise ConnectionError("Connection closed by peer")
                    data.extend(chunk)
                except (BlockingIOError, InterruptedError):
                    continue
            return bytes(data)

    async def async_send_all(self, data: bytes) -> int:
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")
        return await self._async_send(data)

    async def async_recv_all(self, size: int) -> bytes:
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")
        data = bytearray()
        while len(data) < size:
            chunk = await self._async_recv(min(size - len(data), 8192))
            if not chunk:
                raise ConnectionError("Connection closed by peer")
            data.extend(chunk)
        return bytes(data)


class ProtocolSocket(BaseSocket):
    HEADER_SIZE = 32  # 修正：头部大小应为32字节

    def __init__(self, sock=None, io_mode=IOMode.SINGLE):
        super().__init__(sock, io_mode)
        self.sequence = 0
        self.session_id = 0
        # If we're given an existing socket, we should consider it connected
        if sock is not None:
            self.connected = True

    def fileno(self):
        """Return the socket's file descriptor number."""
        return self.socket.fileno()

    def send_message(self, msg_type: MessageType, payload: bytes):
        """Send message using send_all to ensure complete transmission"""
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_send_message for async mode")

        header = self._make_header(msg_type, payload)
        header_bytes = header.to_bytes()

        # Send header using send_all
        self._send_all(header_bytes)

        # Send payload using send_all if it exists
        if payload:
            self._send_all(payload)

        self.sequence += 1
        return True

    async def async_send_message(self, msg_type: MessageType, payload: bytes):
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")
        header = self._make_header(msg_type, payload)
        self.sequence += 1  # 递增序列号
        return await self.async_send_all(header.to_bytes() + payload)

    def receive_message(self):
        """Receive message using recv_all to ensure complete reception"""
        if self.io_mode == IOMode.ASYNC:
            raise RuntimeError("Use async_receive_message for async mode")

        # Read header using recv_all
        header_data = self._recv_all(self.HEADER_SIZE)
        if not header_data:
            raise ConnectionError("Connection closed by peer")

        header = ProtocolHeader.from_bytes(header_data)

        # Read payload using recv_all if payload length > 0
        payload = bytes()
        if header.payload_length > 0:
            payload = self._recv_all(header.payload_length)
            if not payload:
                raise ConnectionError("Connection closed while receiving payload")

        return header, payload

    async def async_receive_message(self):
        if self.io_mode != IOMode.ASYNC:
            raise RuntimeError("Only available in async mode")
        header_data = await self.async_recv_all(HEADERSIZE)
        header = ProtocolHeader.from_bytes(header_data)
        payload = await self.async_recv_all(header.payload_length)
        return header, payload

    def _make_header(self, msg_type, payload):
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=ProtocolVersion.V1,
            msg_type=msg_type,
            payload_length=len(payload),
            sequence_number=self.sequence,
            checksum=zlib.crc32(payload),
            session_id=self.session_id,
        )
