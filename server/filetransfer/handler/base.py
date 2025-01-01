from abc import ABC, abstractmethod
import logging
from typing import Dict, Callable, Set, Optional
from .errors import ChecksumError, ProtocolError, VersionMismatchError
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
from .context import TransferContext


class BaseProtocolHandler(ABC):
    """增强的协议处理器基类"""

    def __init__(self):
        self.state = ProtocolState.INIT
        self.handlers: Dict[MessageType, Callable] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.protocol_version = ProtocolVersion.V1
        self.magic = PROTOCOL_MAGIC
        self.supported_versions: Set[ProtocolVersion] = {ProtocolVersion.V1}
        self._error_handlers: Dict[type, Callable] = {}
        self.session_id: Optional[int] = None
        self.sequence_number: int = 0
        self.transfer_context: Optional[TransferContext] = None

    def register_handler(self, msg_type: MessageType, handler: Callable) -> None:
        """注册消息处理器"""
        self._validate_handler_signature(handler)
        if msg_type in self.handlers:
            raise ValueError(
                f"Handler for message type {msg_type} is already registered"
            )
        self.handlers[msg_type] = handler

    def handle_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """处理收到的消息"""
        try:
            # 1. 基础验证
            if header.magic != self.magic:
                self.logger.error("Invalid magic number")
                return

            if header.version not in self.supported_versions:
                self.logger.error("Protocol version mismatch")
                return

            if not self.verify_checksum(header, payload):
                self.logger.error("Checksum verification failed")
                return

            # 2. 状态检查和消息处理
            # 特殊处理：ERROR 和 LIST_ERROR 消息
            if header.msg_type in {MessageType.ERROR, MessageType.LIST_ERROR}:
                self.state = ProtocolState.ERROR
                self._dispatch_message(header, payload)
                return

            # 特殊处理：HANDSHAKE 消息
            if header.msg_type == MessageType.HANDSHAKE:
                self._dispatch_message(header, payload)
                return

            # ACK 消息可以在任何非 INIT 状态处理
            if header.msg_type == MessageType.ACK:
                if self.state != ProtocolState.INIT:
                    self._dispatch_message(header, payload)
                return

            # 其他消息的状态检查
            if self.state == ProtocolState.INIT:
                self.logger.error("Invalid state for non-handshake message")
                return

            # 3. 根据当前状态和消息类型处理
            can_process = False

            if self.state == ProtocolState.CONNECTED:
                # CONNECTED 状态可以处理的消息
                if header.msg_type in {
                    MessageType.FILE_REQUEST,
                    MessageType.LIST_REQUEST,
                    MessageType.NLST_REQUEST,
                    MessageType.CLOSE,
                    MessageType.RESUME_REQUEST,
                    MessageType.LIST_RESPONSE,
                    MessageType.NLST_RESPONSE,
                }:
                    can_process = True

            elif self.state == ProtocolState.TRANSFERRING:
                # TRANSFERRING 状态可以处理的消息
                if header.msg_type in {
                    MessageType.FILE_DATA,
                    MessageType.FILE_METADATA,
                    MessageType.CHECKSUM_VERIFY,
                    MessageType.CLOSE,
                    MessageType.LIST_RESPONSE,
                    MessageType.NLST_RESPONSE,
                }:
                    can_process = True

            if can_process:
                self._dispatch_message(header, payload)

                # 4. 更新序列号（仅在正常消息处理后）
                if header.msg_type not in {
                    MessageType.HANDSHAKE,
                    MessageType.ERROR,
                    MessageType.LIST_ERROR,
                }:
                    self.sequence_number = header.sequence_number

        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
            self.state = ProtocolState.ERROR

    def _validate_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """验证消息的有效性"""
        if header.magic != self.magic:
            raise ProtocolError("Invalid magic number")

        if header.version not in self.supported_versions:
            raise VersionMismatchError("Protocol version mismatch")

        if not self.verify_checksum(header, payload):
            raise ChecksumError("Checksum verification failed")

    def check_state(
        self, expected_state: ProtocolState, raise_error: bool = False
    ) -> bool:
        """检查当前状态是否符合预期"""
        is_valid = self.state == expected_state
        if not is_valid and raise_error:
            raise ValueError(
                f"Invalid state: expected {expected_state}, but got {self.state}"
            )
        return is_valid

    def _validate_handler_signature(self, handler: Callable) -> None:
        """验证处理器函数签名"""
        import inspect

        sig = inspect.signature(handler)
        params = list(sig.parameters.values())
        if len(params) != 2:
            raise TypeError(
                "Handler must accept exactly 2 parameters (header, payload)"
            )

    @abstractmethod
    def _dispatch_message(self, header: ProtocolHeader, payload: bytes) -> None:
        """分发消息到具体的处理函数"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭处理器，清理资源"""
        self.state = ProtocolState.COMPLETED
        self.handlers.clear()
        self._error_handlers.clear()
        self.session_id = None
        self.transfer_context = None

    def verify_checksum(self, header: ProtocolHeader, payload: bytes) -> bool:
        """验证校验和"""
        expected = header.checksum
        actual = header.calculate_checksum(payload)
        return expected == actual

    def add_supported_version(self, version: ProtocolVersion) -> None:
        """添加支持的协议版本"""
        self.supported_versions.add(version)

    def remove_supported_version(self, version: ProtocolVersion) -> None:
        """移除支持的协议版本"""
        if version in self.supported_versions:
            self.supported_versions.remove(version)
