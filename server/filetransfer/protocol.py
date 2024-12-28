import struct
from enum import IntEnum
from dataclasses import dataclass
import zlib

"""
+----------------+----------------+----------------+----------------+
| magic (2 bytes)| version (2 bytes) | msg_type (4 bytes) | payload_length (4 bytes) |
+----------------+----------------+----------------+----------------+
| sequence_number (4 bytes) | checksum (4 bytes) | chunk_number (4 bytes) | session_id (8 bytes) |
+----------------+----------------+----------------+----------------+
"""
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


# 定义文件列表过滤器
class ListFilter(IntEnum):
    ALL = 0  # 所有文件和目录
    FILES_ONLY = 1  # 只列出文件
    DIRS_ONLY = 2  # 只列出目录


# 定义列表响应格式
class ListResponseFormat(IntEnum):
    BASIC = 1  # 基本信息(文件名)
    DETAIL = 2  # 详细信息(包含大小、时间等)


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
    CLOSE = 9  # 添加关闭连接消息类型
    # 添加文件列表相关消息类型
    LIST_REQUEST = 10  # 请求获取详细文件列表
    LIST_RESPONSE = 11  # 文件列表响应
    NLST_REQUEST = 12  # 请求获取简单文件名列表
    NLST_RESPONSE = 13  # 简单文件名列表响应
    LIST_ERROR = 14  # 列表获取错误


# 定义协议头部数据结构
@dataclass
class ProtocolHeader:
    magic: int  # 魔数，用于标识协议
    version: int  # 协议版本
    msg_type: MessageType  # 消息类型
    payload_length: int  # 负载长度
    sequence_number: int  # 序列号
    checksum: int  # 校验和，使用CRC32
    chunk_number: int = 0  # 数据块编号，默认为0
    session_id: int = 0  # 会话ID，默认为0

    @classmethod
    def from_bytes(cls, header_bytes: bytes) -> "ProtocolHeader":
        """
        从字节数据解析协议头部

        :param header_bytes: 包含头部信息的字节数据
        :return: ProtocolHeader实例
        :raises ValueError: 当头部长度无效或魔数不匹配时抛出
        """
        if len(header_bytes) < 32:  # 基础头部长度检查
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
        """
        将协议头部转换为字节数据

        :return: 包含头部信息的字节数据
        """
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
        """
        计算负载数据的CRC32校验和

        :param payload: 负载数据
        :return: CRC32校验和
        """
        return zlib.crc32(payload)
