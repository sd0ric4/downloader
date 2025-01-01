import struct
from enum import IntEnum, auto
from dataclasses import dataclass
import zlib
import uuid


# 定义协议版本
class ProtocolVersion(IntEnum):
    V1 = 1
    V2 = 2  # 新版本


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
    # 基础消息类型
    HANDSHAKE = 1
    HANDSHAKE_RESPONSE = 2
    CAPABILITIES_REQUEST = 3
    CAPABILITIES_RESPONSE = 4
    CLOSE = 9  # 关闭连接的消息类型

    # 文件操作消息类型
    FILE_REQUEST = 10
    FILE_METADATA = 11
    FILE_DATA = 15  # 修改为不同的值
    FILE_CONTROL = 13

    # 控制消息类型
    ERROR = 20
    ACK = 21
    KEEPALIVE = 22
    RESUME_REQUEST = 8

    # 高级文件列表
    LIST_REQUEST = 30
    LIST_RESPONSE = 31
    NLST_REQUEST = 32  # 修改为不同的值
    NLST_RESPONSE = 33  # 修改为不同的值
    LIST_ERROR = 14

    # 传输控制
    TRANSFER_INIT = 40
    TRANSFER_RESUME = 41
    TRANSFER_PAUSE = 42
    TRANSFER_CANCEL = 43
    TRANSFER_COMPLETE = 44


# 协议魔数和版本
PROTOCOL_MAGIC = 0x4442  # "DB" for DarkBird
PROTOCOL_VERSION = ProtocolVersion.V2  # 使用枚举版本


# 更丰富的错误类型
class ErrorType(IntEnum):
    UNKNOWN = 0
    PROTOCOL_MISMATCH = 1
    AUTHENTICATION_FAILED = 2
    PERMISSION_DENIED = 3
    FILE_NOT_FOUND = 4
    TRANSFER_INTERRUPTED = 5
    STORAGE_FULL = 6
    NETWORK_ERROR = 7


# 传输方向和模式
class TransferDirection(IntEnum):
    UPLOAD = 1
    DOWNLOAD = 2


class TransferMode(IntEnum):
    BINARY = 1
    TEXT = 2


# 协议头部数据结构y
@dataclass
class ProtocolHeader:
    magic: int = PROTOCOL_MAGIC
    version: int = PROTOCOL_VERSION
    msg_type: MessageType = MessageType.HANDSHAKE
    payload_length: int = 0
    sequence_number: int = 0
    checksum: int = 0
    transfer_direction: TransferDirection = TransferDirection.DOWNLOAD
    transfer_mode: TransferMode = TransferMode.BINARY
    timestamp: int = 0
    session_id: bytes = None

    def __post_init__(self):
        # 处理session_id
        if self.session_id is None:
            import uuid

            self.session_id = uuid.uuid4().bytes

        # 尝试转换session_id为bytes
        if not isinstance(self.session_id, bytes):
            try:
                # 如果是整数，尝试转换为bytes
                if isinstance(self.session_id, int):
                    self.session_id = self.session_id.to_bytes(16, "big")
                else:
                    self.session_id = str(self.session_id).encode("utf-8")
            except:
                # 转换失败，使用uuid
                import uuid

                self.session_id = uuid.uuid4().bytes

        # 确保session_id是16字节
        if len(self.session_id) < 16:
            self.session_id = self.session_id.ljust(16, b"\0")
        elif len(self.session_id) > 16:
            self.session_id = self.session_id[:16]

    @classmethod
    def from_bytes(cls, header_bytes: bytes) -> "ProtocolHeader":
        """从字节数据解析协议头部"""
        if len(header_bytes) < 48:  # 增加了头部长度
            raise ValueError("Invalid header length")

        (
            magic,
            version,
            msg_type,
            payload_len,
            seq_num,
            checksum,
            transfer_direction,
            transfer_mode,
            timestamp,
        ) = struct.unpack("!HHIIIIBBQ", header_bytes[:36])

        session_id = header_bytes[36:52]

        if magic != PROTOCOL_MAGIC:
            raise ValueError("Invalid protocol magic number")

        return cls(
            magic=magic,
            version=version,
            msg_type=MessageType(msg_type),
            payload_length=payload_len,
            sequence_number=seq_num,
            checksum=checksum,
            transfer_direction=TransferDirection(transfer_direction),
            transfer_mode=TransferMode(transfer_mode),
            session_id=session_id,
            timestamp=timestamp,
            chunk_number=0,  # 默认值
        )

    def to_bytes(self) -> bytes:
        """将协议头部转换为字节数据"""
        return struct.pack(
            "!HHIIIIBBQ16s",
            self.magic,
            self.version,
            self.msg_type,
            self.payload_length,
            self.sequence_number,
            self.checksum,
            self.transfer_direction,
            self.transfer_mode,
            self.timestamp,
            self.session_id,
        )

    def calculate_checksum(self, payload: bytes) -> int:
        """计算负载数据的校验和"""
        return zlib.crc32(payload)


# 错误消息结构
@dataclass
class ErrorMessage:
    error_type: ErrorType
    error_code: int
    description: str

    def to_bytes(self) -> bytes:
        """序列化错误消息"""
        desc_bytes = self.description.encode("utf-8")
        return struct.pack(
            f"!IIH{len(desc_bytes)}s",
            self.error_type,
            self.error_code,
            len(desc_bytes),
            desc_bytes,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ErrorMessage":
        """反序列化错误消息"""
        error_type, error_code, desc_len = struct.unpack("!IIH", data[:10])
        description = data[10 : 10 + desc_len].decode("utf-8")
        return cls(ErrorType(error_type), error_code, description)


# 能力描述
@dataclass
class ProtocolCapabilities:
    max_chunk_size: int
    max_concurrent_transfers: int
    supports_resume: bool
    supports_encryption: bool

    def to_bytes(self) -> bytes:
        """序列化协议能力"""
        return struct.pack(
            "!IIBB",
            self.max_chunk_size,
            self.max_concurrent_transfers,
            int(self.supports_resume),
            int(self.supports_encryption),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ProtocolCapabilities":
        """反序列化协议能力"""
        max_chunk_size, max_concurrent, supports_resume, supports_encryption = (
            struct.unpack("!IIBB", data)
        )
        return cls(
            max_chunk_size,
            max_concurrent,
            bool(supports_resume),
            bool(supports_encryption),
        )


# 保留了原有的文件列表请求结构，并做了小的改进
@dataclass
class ListRequest:
    format: ListResponseFormat
    filter: ListFilter
    path: str = "/"
    depth: int = 1  # 增加递归深度支持

    def to_bytes(self) -> bytes:
        """序列化为字节"""
        path_bytes = self.path.encode("utf-8")
        return struct.pack(
            f"!III{len(path_bytes)}s", self.format, self.filter, self.depth, path_bytes
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ListRequest":
        """从字节反序列化"""
        format_type, filter_type, depth = struct.unpack("!III", data[:12])
        path = data[12:].decode("utf-8") if len(data) > 12 else "/"
        return cls(
            ListResponseFormat(format_type), ListFilter(filter_type), path, depth
        )
