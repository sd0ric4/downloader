import logging
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, Optional, Generator

from ..protocol import (
    MessageType,
    ProtocolHeader,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
)
from ..protocol.tools import MessageBuilder


@dataclass
class RawMessage:
    """原始消息包装器"""

    header_bytes: bytes
    payload_bytes: bytes

    def to_bytes(self) -> bytes:
        """将消息转换为完整的字节流"""
        return self.header_bytes + self.payload_bytes


class SocketTransferUtils:
    """Socket传输工具类"""

    def __init__(self, chunk_size: int = 8192):
        self.message_builder = MessageBuilder()
        self.chunk_size = chunk_size
        self.logger = logging.getLogger(__name__)

    def create_handshake_message(self) -> RawMessage:
        """创建握手消息"""
        header_bytes, payload = self.message_builder.build_handshake()
        return RawMessage(header_bytes, payload)

    def create_file_request(self, filename: str) -> RawMessage:
        """创建文件请求消息"""
        header_bytes, payload = self.message_builder.build_file_request(filename)
        return RawMessage(header_bytes, payload)

    def create_file_chunks(self, file_path: str) -> Generator[RawMessage, None, None]:
        """生成文件数据块消息流"""
        file_path = Path(file_path)
        chunk_number = 0

        with open(file_path, "rb") as f:
            while True:
                chunk_data = f.read(self.chunk_size)
                if not chunk_data:
                    break

                header = self._create_data_header(chunk_data, chunk_number)
                yield RawMessage(header.to_bytes(), chunk_data)
                chunk_number += 1

    def create_resume_request(self, filename: str, offset: int) -> RawMessage:
        """创建续传请求消息"""
        header_bytes, payload = self.message_builder.build_resume_request(
            filename, offset
        )
        return RawMessage(header_bytes, payload)

    def create_checksum_verify(self, file_path: str) -> RawMessage:
        """创建校验和验证消息"""
        checksum = self._calculate_file_checksum(Path(file_path))
        header_bytes, payload = self.message_builder.build_checksum_verify(checksum)
        return RawMessage(header_bytes, payload)

    def create_list_request(
        self,
        path: str = "",
        list_format: ListResponseFormat = ListResponseFormat.DETAIL,
        list_filter: ListFilter = ListFilter.ALL,
    ) -> RawMessage:
        """创建列表请求消息"""
        list_req = ListRequest(format=list_format, filter=list_filter, path=path)
        payload = list_req.to_bytes()
        header = self._create_header(MessageType.LIST_REQUEST, len(payload))
        return RawMessage(header.to_bytes(), payload)

    def _create_header(
        self, msg_type: MessageType, payload_length: int = 0, chunk_number: int = 0
    ) -> ProtocolHeader:
        """创建消息头"""
        return ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=1,
            msg_type=msg_type,
            payload_length=payload_length,
            sequence_number=self.message_builder.sequence_number,
            checksum=0,
            chunk_number=chunk_number,
            session_id=self.message_builder.session_id,
        )

    def _create_data_header(self, data: bytes, chunk_number: int) -> ProtocolHeader:
        """创建数据块消息头"""
        header = self._create_header(MessageType.FILE_DATA, len(data), chunk_number)
        header.checksum = header.calculate_checksum(data)
        return header

    @staticmethod
    def _calculate_file_checksum(file_path: Path) -> int:
        """计算文件校验和"""
        with open(file_path, "rb") as f:
            return zlib.crc32(f.read())

    def start_session(self) -> None:
        """开始新会话"""
        self.message_builder.start_session()


# 使用示例:
"""
# 创建工具实例
transfer = SocketTransferUtils()
transfer.start_session()

# 发送握手消息
handshake = transfer.create_handshake_message()
socket.send(handshake.to_bytes())

# 发送文件请求
file_req = transfer.create_file_request("example.txt")
socket.send(file_req.to_bytes())

# 发送文件数据
for chunk in transfer.create_file_chunks("local_file.txt"):
    socket.send(chunk.to_bytes())

# 发送校验和验证
verify = transfer.create_checksum_verify("local_file.txt")
socket.send(verify.to_bytes())
"""
