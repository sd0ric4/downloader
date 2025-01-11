import asyncio
import socket
import select
import threading
from pathlib import Path
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

from filetransfer.protocol import MessageType
from filetransfer.protocol.tools import MessageBuilder
from filetransfer.network import ProtocolSocket
from filetransfer.server.socket_utils import (
    ChunkTracker,
    DownloadManager,
    NetworkTransferUtils,
)


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
        self.root_dir = Path("/tmp/client_root")  # 客户端根目录
        self.temp_dir = Path("/tmp/client_temp")  # 客户端临时目录
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _handshake(self, protocol_socket: ProtocolSocket) -> bool:
        """执行握手"""
        try:
            header_bytes, payload = self.message_builder.build_handshake()
            protocol_socket.send_message(header_bytes, payload)

            response_header, response_payload = protocol_socket.receive_message()
            return response_header.msg_type == MessageType.HANDSHAKE
        except Exception as e:
            self.logger.error(f"握手失败: {e}")
            return False


class SingleThreadClient(BaseClient):
    def __init__(self, host: str, port: int):
        super().__init__(host, port)
        self.socket = None
        self.protocol_socket = None
        self.transfer_utils = None
        self.download_manager = None

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.protocol_socket = ProtocolSocket(self.socket)
            self.transfer_utils = NetworkTransferUtils(self.protocol_socket)
            self.download_manager = DownloadManager(self.transfer_utils, self.temp_dir)
            self._connected = True
            return self._connected
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            return False

    def upload_file(self, file_path: str, dest_filename: str = None) -> bool:
        if not self._connected:
            return False
        result = self.transfer_utils.send_file(file_path, dest_filename)
        return result.success

    def resume_upload(
        self, file_path: str, dest_filename: str, offset: int, chunk_number: int
    ) -> bool:
        try:
            result = self.transfer_utils.resume_transfer(
                file_path, dest_filename, offset, chunk_number
            )
            if not result.success:
                self.logger.error(f"续传失败: {result.message}")
            return result.success
        except Exception as e:
            self.logger.error(f"续传异常: {str(e)}")
            return False

    def download_file(self, remote_path: str, local_path: str) -> bool:
        """
        下载文件，支持断点续传
        """
        if not self._connected:
            return False

        try:
            result = self.download_manager.download_file(remote_path, local_path)

            if not result.success:
                self.logger.error(f"下载失败: {result.message}")
                return False

            self.logger.info(
                f"下载成功 - {remote_path} -> {local_path}"
                f"(大小: {result.transferred_size} bytes)"
            )
            return True

        except Exception as e:
            self.logger.error(f"下载异常: {str(e)}")
            return False

    def get_download_progress(self, local_path: str) -> Optional[float]:
        """
        获取下载进度
        返回: 0.0-1.0 的进度值，如果无法获取则返回 None
        """
        try:
            state_file = self.temp_dir / f"{Path(local_path).name}.state"
            self.logger.info(f"state_file: {state_file}")
            if not state_file.exists():
                return None

            tracker = ChunkTracker.load_state(state_file)
            if tracker:
                return len(tracker.received_chunks) / tracker.total_chunks
            return None

        except Exception as e:
            self.logger.error(f"获取下载进度失败: {str(e)}")
            return None

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


# 使用示例
"""
# 创建客户端实例
client = SingleThreadClient("localhost", 8000)
client.connect()

# 下载文件（支持断点续传）
success = client.download_file("/remote/large_file.zip", "./local/large_file.zip")

# 查看下载进度
progress = client.get_download_progress("./local/large_file.zip")
if progress is not None:
    print(f"下载进度: {progress * 100:.2f}%")

# 上传文件
client.upload_file("local.txt", "remote.txt")

# 从指定块号和偏移量续传
client.resume_upload("local.txt", "remote.txt", offset=1024, chunk_number=5)

# 列出文件
files = client.list_files(".", recursive=True)
for file_info in files:
    print(f"文件名: {file_info.name}, 大小: {file_info.size}")

# 关闭连接
client.close()
"""
