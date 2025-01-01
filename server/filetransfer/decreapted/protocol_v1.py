import struct
from enum import IntEnum
from dataclasses import dataclass
import zlib

# 添加协议魔数
PROTOCOL_MAGIC = 0x4442  # "DB" for DarkBird


# 定义协议版本
class ProtocolVersion(IntEnum):
    V1 = 1


# 定义协议状态
class ProtocolState(IntEnum):
    INIT = 0
    CONNECTED = 1
    TRANSFERRING = 2
    COMPLETED = 3
    ERROR = 4


# 定义消息类型
class MessageType(IntEnum):
    HANDSHAKE = 1
    FILE_REQUEST = 2
    FILE_METADATA = 3
    FILE_DATA = 4
    CHECKSUM_VERIFY = 5
    ERROR = 6
    ACK = 7
    RESUME_REQUEST = 8
    CLOSE = 9

    # 文件列表相关消息类型
    LIST_REQUEST = 10  # 详细文件列表请求
    LIST_RESPONSE = 11  # 文件列表响应
    NLST_REQUEST = 12  # 简单文件名列表请求
    NLST_RESPONSE = 13  # 简单文件名列表响应
    LIST_ERROR = 14  # 列表错误响应


# 定义文件列表过滤器
class ListFilter(IntEnum):
    ALL = 0  # 所有文件和目录
    FILES_ONLY = 1  # 只列出文件
    DIRS_ONLY = 2  # 只列出目录


# 定义列表响应格式
class ListResponseFormat(IntEnum):
    BASIC = 1  # 基本信息(文件名)
    DETAIL = 2  # 详细信息(包含大小、时间等)


# 定义文件列表请求结构
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


# 定义协议头部数据结构
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

        (
            magic,
            version,
            msg_type,
            payload_len,
            seq_num,
            checksum,
            chunk_num,
            session_id,
        ) = struct.unpack("!HHIIIIIQ", header_bytes)

        if magic != PROTOCOL_MAGIC:
            raise ValueError("Invalid protocol magic number")

        return cls(
            magic,
            version,
            MessageType(msg_type),
            payload_len,
            seq_num,
            checksum,
            chunk_num,
            session_id,
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
