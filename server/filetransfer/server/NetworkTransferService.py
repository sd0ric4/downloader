import socket
import logging
from pathlib import Path
from typing import Optional, Tuple

from .utils import SocketTransferUtils, RawMessage
from ..protocol import (
    MessageType,
    ProtocolHeader,
    ListResponseFormat,
    ListFilter,
)


class NetworkTransferService:
    """网络传输服务，集成 SocketTransferUtils 和原有的 TransferService"""

    def __init__(
        self, host: str, port: int, root_dir: str = ".", chunk_size: int = 8192
    ):
        self.host = host
        self.port = port
        self.root_dir = Path(root_dir)
        self.socket = None
        self.transfer_utils = SocketTransferUtils(chunk_size=chunk_size)
        self.logger = logging.getLogger(__name__)

    def connect(self) -> bool:
        """建立连接并进行握手"""
        try:
            # 创建socket连接
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))

            # 开始新会话
            self.transfer_utils.start_session()

            # 发送握手消息
            handshake = self.transfer_utils.create_handshake_message()
            success = self._send_and_verify(handshake)

            return success
        except Exception as e:
            self.logger.error(f"连接失败: {str(e)}")
            return False

    def send_file(self, file_path: str, dest_filename: Optional[str] = None) -> bool:
        """发送文件

        Args:
            file_path: 源文件路径
            dest_filename: 目标文件名，默认使用源文件名

        Returns:
            bool: 是否成功
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                self.logger.error("文件不存在")
                return False

            dest_filename = dest_filename or file_path.name

            # 1. 发送文件请求
            file_req = self.transfer_utils.create_file_request(dest_filename)
            if not self._send_and_verify(file_req):
                return False

            # 2. 分块发送文件
            for chunk in self.transfer_utils.create_file_chunks(str(file_path)):
                if not self._send_and_verify(chunk):
                    return False

            # 3. 发送校验和验证
            verify = self.transfer_utils.create_checksum_verify(str(file_path))
            return self._send_and_verify(verify)

        except Exception as e:
            self.logger.error(f"发送文件失败: {str(e)}")
            return False

    def resume_transfer(self, file_path: str, dest_filename: str, offset: int) -> bool:
        """断点续传

        Args:
            file_path: 源文件路径
            dest_filename: 目标文件名
            offset: 续传的起始位置

        Returns:
            bool: 是否成功
        """
        try:
            # 1. 发送续传请求
            resume_req = self.transfer_utils.create_resume_request(
                dest_filename, offset
            )
            if not self._send_and_verify(resume_req):
                return False

            # 2. 从偏移位置开始发送文件块
            path = Path(file_path)
            file_size = path.stat().st_size
            if offset >= file_size:
                self.logger.error("偏移量超出文件大小")
                return False

            # 调整分块起始位置
            start_chunk = offset // self.transfer_utils.chunk_size
            for chunk in self.transfer_utils.create_file_chunks(str(path)):
                if not self._send_and_verify(chunk):
                    return False

            # 3. 发送校验和验证
            verify = self.transfer_utils.create_checksum_verify(str(path))
            return self._send_and_verify(verify)

        except Exception as e:
            self.logger.error(f"续传失败: {str(e)}")
            return False

    def list_directory(
        self,
        path: str = "",
        list_format: ListResponseFormat = ListResponseFormat.DETAIL,
        list_filter: ListFilter = ListFilter.ALL,
    ) -> Optional[bytes]:
        """获取目录列表

        Args:
            path: 要列出的目录路径
            list_format: 列表格式
            list_filter: 过滤条件

        Returns:
            Optional[bytes]: 目录列表响应数据
        """
        try:
            # 发送列表请求
            list_req = self.transfer_utils.create_list_request(
                path, list_format, list_filter
            )
            if self._send_and_verify(list_req):
                # 接收并返回响应数据
                return self._receive_response()
            return None
        except Exception as e:
            self.logger.error(f"获取目录列表失败: {str(e)}")
            return None

    def close(self):
        """关闭连接"""
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                self.logger.error(f"关闭连接失败: {str(e)}")
            finally:
                self.socket = None

    def _send_and_verify(self, message: RawMessage) -> bool:
        """发送消息并验证响应"""
        try:
            if not self.socket:
                raise ConnectionError("未建立连接")

            # 发送消息
            self.socket.sendall(message.to_bytes())

            # 接收响应
            response = self._receive_response()
            if not response:
                return False

            # 解析响应头
            header = ProtocolHeader.from_bytes(response[: ProtocolHeader.SIZE])

            # 检查响应类型
            return header.msg_type in [MessageType.ACK, MessageType.FILE_ACCEPT]

        except Exception as e:
            self.logger.error(f"发送消息失败: {str(e)}")
            return False

    def _receive_response(self, buffer_size: int = 1024) -> Optional[bytes]:
        """接收响应数据"""
        try:
            # 首先接收消息头
            header_data = self.socket.recv(ProtocolHeader.SIZE)
            if not header_data or len(header_data) < ProtocolHeader.SIZE:
                return None

            header = ProtocolHeader.from_bytes(header_data)

            # 如果有负载数据，继续接收
            payload = b""
            remaining = header.payload_length
            while remaining > 0:
                chunk = self.socket.recv(min(buffer_size, remaining))
                if not chunk:
                    return None
                payload += chunk
                remaining -= len(chunk)

            return header_data + payload

        except Exception as e:
            self.logger.error(f"接收响应失败: {str(e)}")
            return None


# 使用示例：
"""
# 创建服务实例
service = NetworkTransferService("localhost", 8000)

# 连接服务器
if service.connect():
    try:
        # 发送文件
        if service.send_file("local_file.txt", "remote_file.txt"):
            print("文件发送成功")
            
        # 获取目录列表
        if response := service.list_directory("/some/path"):
            print("目录列表获取成功")
            
    finally:
        service.close()
"""
