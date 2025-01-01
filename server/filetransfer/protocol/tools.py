import struct
import logging
from typing import List, Tuple, Optional
from .types import (
    MessageType,
    ProtocolVersion,
    ListFilter,
    ListResponseFormat,
    ProtocolState,
)
from .constants import PROTOCOL_MAGIC
from .messages import ProtocolHeader, ListRequest

logger = logging.getLogger(__name__)


class MessageBuilder:
    """协议消息构建器"""

    def __init__(self, version: int = ProtocolVersion.V1):
        self.version = version
        self.sequence_number = 0
        self.session_id = 0
        self.state = ProtocolState.INIT

    def _build_header(
        self, msg_type: MessageType, payload: bytes, chunk_number: int = 0
    ) -> ProtocolHeader:
        """构建消息头"""
        header = ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=self.version,
            msg_type=msg_type,
            payload_length=len(payload),
            sequence_number=self.sequence_number,
            checksum=0,  # 临时占位
            chunk_number=chunk_number,
            session_id=self.session_id,
        )
        header.checksum = header.calculate_checksum(payload)
        self.sequence_number += 1
        return header

    def build_message(
        self, msg_type: MessageType, payload: bytes = b""
    ) -> Tuple[bytes, bytes]:
        """构建完整消息"""
        try:
            header = self._build_header(msg_type, payload)
            return header.to_bytes(), payload
        except Exception as e:
            logger.error(f"Error building message: {e}")
            raise

    # 基本消息构建方法
    def build_handshake(self) -> Tuple[bytes, bytes]:
        """构建握手消息"""
        payload = struct.pack("!I", self.version)
        return self.build_message(MessageType.HANDSHAKE, payload)

    def build_file_request(self, filename: str) -> Tuple[bytes, bytes]:
        """构建文件请求消息"""
        payload = filename.encode("utf-8")
        return self.build_message(MessageType.FILE_REQUEST, payload)

    def build_ack(self, received_seq: int) -> Tuple[bytes, bytes]:
        """构建确认消息"""
        payload = struct.pack("!I", received_seq)
        return self.build_message(MessageType.ACK, payload)

    def build_chunk_ack(
        self, received_seq: int, chunk_number: int
    ) -> Tuple[bytes, bytes]:
        """构建分块传输的确认消息

        Args:
            received_seq: 接收到的序列号
            chunk_number: 块号
        """
        # 构建消息头
        payload = struct.pack("!I", received_seq)
        header = self._build_header(MessageType.ACK, payload, chunk_number)
        return header.to_bytes(), payload

    # 新增: 列表相关消息构建方法
    def build_list_request(
        self,
        format: ListResponseFormat = ListResponseFormat.BASIC,
        filter: ListFilter = ListFilter.ALL,
        path: str = "/",
    ) -> Tuple[bytes, bytes]:
        """构建详细文件列表请求消息"""
        list_req = ListRequest(format=format, filter=filter, path=path)
        payload = list_req.to_bytes()
        return self.build_message(MessageType.LIST_REQUEST, payload)

    def build_nlst_request(
        self, filter: ListFilter = ListFilter.ALL, path: str = "/"
    ) -> Tuple[bytes, bytes]:
        """构建简单文件名列表请求消息"""
        payload = struct.pack("!I", filter) + path.encode("utf-8")
        return self.build_message(MessageType.NLST_REQUEST, payload)

    # 新增: 错误和控制消息
    def build_error(self, error_msg: str) -> Tuple[bytes, bytes]:
        """构建错误消息"""
        payload = error_msg.encode("utf-8")
        return self.build_message(MessageType.ERROR, payload)

    def build_close(self) -> Tuple[bytes, bytes]:
        """构建关闭连接消息"""
        return self.build_message(MessageType.CLOSE, b"")

    def build_file_metadata(
        self, filename: str, size: int, checksum: int
    ) -> Tuple[bytes, bytes]:
        """构建文件元数据消息"""
        payload = struct.pack("!QI", size, checksum) + filename.encode("utf-8")
        return self.build_message(MessageType.FILE_METADATA, payload)

    def build_file_data(self, data: bytes, chunk_number: int) -> Tuple[bytes, bytes]:
        """构建文件数据消息"""
        # 直接传 data 作为 payload
        header = self._build_header(MessageType.FILE_DATA, data, chunk_number)
        return header.to_bytes(), data

    def build_checksum_verify(self, checksum: int) -> Tuple[bytes, bytes]:
        """构建校验和验证消息"""
        payload = struct.pack("!I", checksum)
        return self.build_message(MessageType.CHECKSUM_VERIFY, payload)

    def build_resume_request(self, filename: str, offset: int) -> Tuple[bytes, bytes]:
        """构建断点续传请求消息"""
        payload = struct.pack("!Q", offset) + filename.encode("utf-8")
        return self.build_message(MessageType.RESUME_REQUEST, payload)

    def build_list_response(
        self, entries: List[Tuple[str, int, int, bool]], format: ListResponseFormat
    ) -> Tuple[bytes, bytes]:
        """
        构建文件列表响应消息
        entries: List of (filename, size, mtime, is_dir)
        """
        payload = struct.pack("!I", format)
        for name, size, mtime, is_dir in entries:
            entry_data = struct.pack("!?QQ", is_dir, size, mtime)
            name_bytes = name.encode("utf-8")
            entry_data += struct.pack("!H", len(name_bytes)) + name_bytes
            payload += entry_data
        return self.build_message(MessageType.LIST_RESPONSE, payload)

    def build_nlst_response(self, file_names: List[str]) -> Tuple[bytes, bytes]:
        """构建简单文件名列表响应消息"""
        payload = b"\n".join(name.encode("utf-8") for name in file_names)
        return self.build_message(MessageType.NLST_RESPONSE, payload)

    def build_list_error(self, error_msg: str) -> Tuple[bytes, bytes]:
        """构建列表错误响应消息"""
        payload = error_msg.encode("utf-8")
        return self.build_message(MessageType.LIST_ERROR, payload)

    # 新增: 会话管理方法®
    def start_session(self) -> None:
        """开始新会话"""
        self.session_id += 1
        self.sequence_number = 0
        self.state = ProtocolState.INIT

    def reset_sequence(self) -> None:
        """重置序列号"""
        self.sequence_number = 0

    # 新增: 状态检查方法
    def check_state(self, expected_state: ProtocolState) -> bool:
        """检查当前状态是否符合预期"""
        return self.state == expected_state

    def verify_message(self, header: ProtocolHeader, payload: bytes) -> bool:
        """验证消息的完整性"""
        expected_checksum = header.calculate_checksum(payload)
        return header.checksum == expected_checksum

    def validate_state_transition(self, msg_type: MessageType) -> bool:
        """验证状态转换的合法性"""
        valid_transitions = {
            ProtocolState.INIT: [MessageType.HANDSHAKE],
            ProtocolState.CONNECTED: [
                MessageType.FILE_REQUEST,
                MessageType.LIST_REQUEST,
                MessageType.NLST_REQUEST,
                MessageType.CLOSE,
                MessageType.RESUME_REQUEST,
                MessageType.LIST_RESPONSE,
                MessageType.NLST_RESPONSE,
            ],
            ProtocolState.TRANSFERRING: [
                MessageType.FILE_DATA,
                MessageType.FILE_METADATA,
                MessageType.CHECKSUM_VERIFY,
                MessageType.ACK,
                MessageType.CLOSE,
                MessageType.LIST_RESPONSE,
                MessageType.NLST_RESPONSE,
                MessageType.FILE_REQUEST,
            ],
        }
        return msg_type in valid_transitions.get(self.state, [])
