import struct
import zlib
from dataclasses import dataclass
from typing import Optional
from .types import MessageType, ProtocolVersion, ListFilter, ListResponseFormat
from .constants import PROTOCOL_MAGIC


@dataclass
class ProtocolHeader:
    magic: int  # 魔数
    version: int  # 协议版本
    msg_type: MessageType  # 消息类型
    payload_length: int  # 负载长度
    sequence_number: int  # 序列号
    checksum: int  # 校验和
    chunk_number: int = 0  # 数据块编号
    session_id: int = 0  # 会话ID

    @classmethod
    def from_bytes(cls, header_bytes: bytes) -> "ProtocolHeader":
        """从字节数据解析协议头部"""
        if len(header_bytes) < 32:
            raise ValueError("Invalid header length")

        values = struct.unpack("!HHIIIIIQ", header_bytes)

        if values[0] != PROTOCOL_MAGIC:
            raise ValueError("Invalid protocol magic number")

        return cls(
            magic=values[0],
            version=values[1],
            msg_type=MessageType(values[2]),
            payload_length=values[3],
            sequence_number=values[4],
            checksum=values[5],
            chunk_number=values[6],
            session_id=values[7],
        )

    def to_bytes(self) -> bytes:
        """将协议头部转换为字节数据"""
        return struct.pack(
            "!HHIIIIIQ",
            self.magic,
            self.version,
            self.msg_type,
            self.payload_length,
            self.sequence_number,
            self.checksum,
            self.chunk_number,
            self.session_id,
        )

    def calculate_checksum(self, payload: bytes) -> int:
        """计算负载数据的校验和"""
        return zlib.crc32(payload)


@dataclass
class ListRequest:
    format: ListResponseFormat
    filter: ListFilter
    path: str = "/"  # 请求的目录路径

    def to_bytes(self) -> bytes:
        """序列化为字节"""
        path_bytes = self.path.encode("utf-8")
        return struct.pack("!II", self.format, self.filter) + path_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "ListRequest":
        """从字节反序列化"""
        format_type, filter_type = struct.unpack("!II", data[:8])
        path = data[8:].decode("utf-8") if len(data) > 8 else "/"
        return cls(ListResponseFormat(format_type), ListFilter(filter_type), path)
