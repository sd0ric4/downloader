import asyncio
import socket
import select
import threading
from pathlib import Path
import logging
from typing import Optional, List, Tuple
import struct
from dataclasses import dataclass

from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ListRequest,
    ListFilter,
    PROTOCOL_MAGIC,
)
from filetransfer.protocol.tools import MessageBuilder
from filetransfer.network import ProtocolSocket, IOMode
from filetransfer.server.socket_utils import NetworkTransferUtils


@dataclass
class FileInfo:
    name: str
    size: int
    is_directory: bool
    modified_time: float


class BaseClient:
    """基础客户端类"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.message_builder = MessageBuilder()
        self.logger = logging.getLogger(__name__)
        self._connected = False
        self.root_dir = "/tmp/client_root"  # 客户端根目录
        self.temp_dir = "/tmp/client_temp"  # 客户端临时目录
        Path(self.root_dir).mkdir(parents=True, exist_ok=True)
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)

    def _handshake(self, protocol_socket: ProtocolSocket) -> bool:
        """执行握手"""
        try:
            header_bytes, payload = self.message_builder.build_handshake()
            protocol_socket.send_message(header_bytes, payload)

            response_header, response_payload = protocol_socket.receive_message()
            return response_header.msg_type == MessageType.HANDSHAKE
        except Exception as e:
            self.logger.error(f"Handshake failed: {e}")
            return False


class SingleThreadClient(BaseClient):
    def __init__(self, host: str, port: int):
        super().__init__(host, port)
        self.socket = None
        self.protocol_socket = None
        self.transfer_utils = None

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.protocol_socket = ProtocolSocket(self.socket)
            self.transfer_utils = NetworkTransferUtils(self.protocol_socket)
            self._connected = True
            return self._connected
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False

    def upload_file(self, file_path: str, dest_filename: str = None) -> bool:
        if not self._connected:
            return False
        result = self.transfer_utils.send_file(file_path, dest_filename)
        return result.success

    def resume_upload(self, file_path: str, dest_filename: str, offset: int) -> bool:
        try:
            result = self.transfer_utils.resume_transfer(
                file_path, dest_filename, offset
            )
            if not result.success:
                self.logger.error(f"续传失败: {result.message}")  # 添加错误消息
            return result.success
        except Exception as e:
            self.logger.error(f"续传异常: {str(e)}")  # 添加异常信息
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        if not self._connected:
            return False
        result = self.transfer_utils.download_file(remote_path, local_path)
        return result.success

    def list_files(self, path: str = ".", recursive: bool = False) -> List[FileInfo]:
        if not self._connected:
            return []
        result = self.transfer_utils.list_directory(path, recursive=recursive)
        return [
            FileInfo(name, size, is_dir, mtime)
            for name, size, mtime, is_dir in result.entries
        ]

    def close(self):
        if self.protocol_socket:
            self.protocol_socket.close()
        if self.socket:
            self.socket.close()
        self._connected = False


class ThreadedClient(BaseClient):
    def __init__(self, host: str, port: int):
        super().__init__(host, port)
        self.socket = None
        self.protocol_socket = None
        self.transfer_utils = None
        self._lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.protocol_socket = ProtocolSocket(self.socket, io_mode=IOMode.THREADED)
            self.transfer_utils = NetworkTransferUtils(self.protocol_socket)
            self._connected = True
            return self._connected
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False

    def upload_file(self, file_path: str, dest_filename: str = None) -> bool:
        with self._lock:
            if not self._connected:
                return False
            result = self.transfer_utils.send_file(file_path, dest_filename)
            return result.success

    def resume_upload(self, file_path: str, dest_filename: str, offset: int) -> bool:
        with self._lock:
            if not self._connected:
                return False
            result = self.transfer_utils.resume_transfer(
                file_path, dest_filename, offset
            )
            return result.success

    # 测试通过
    def download_file(self, remote_path: str, local_path: str) -> bool:
        with self._lock:
            if not self._connected:
                return False
            result = self.transfer_utils.download_file(remote_path, local_path)
            return result.success

    # 测试通过
    def list_files(self, path: str = ".", recursive: bool = False) -> List[FileInfo]:
        with self._lock:
            if not self._connected:
                return []
            result = self.transfer_utils.list_directory(path, recursive=recursive)
            return [
                FileInfo(name, size, is_dir, mtime)
                for name, size, mtime, is_dir in result.entries
            ]

    def close(self):
        with self._lock:
            if self.protocol_socket:
                self.protocol_socket.close()
            if self.socket:
                self.socket.close()
            self._connected = False


# 使用示例
"""
# 单线程客户端
client = SingleThreadClient("localhost", 8000)
client.connect()
client.upload_file("local.txt", "remote.txt")
client.resume_upload("local.txt", "remote.txt", offset=1024)
client.download_file("remote.txt", "local_copy.txt")
files = client.list_files(".", recursive=True)
client.close()

# 异步客户端
async def main():
    client = AsyncClient("localhost", 8000)
    await client.connect()
    await client.upload_file("local.txt", "remote.txt")
    await client.resume_upload("local.txt", "remote.txt", offset=1024)
    await client.download_file("remote.txt", "local_copy.txt")
    files = await client.list_files(".", recursive=True)
    await client.close()

asyncio.run(main())
"""
