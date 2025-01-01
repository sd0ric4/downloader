from pathlib import Path
import struct
from typing import Optional, Dict, Tuple, List
import logging
from dataclasses import dataclass
from datetime import datetime
import os
import zlib
from .file_manager import FileManager, TransferContext
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ListRequest,
    ListFilter,
    PROTOCOL_MAGIC,
)
from filetransfer.protocol.tools import MessageBuilder


from pathlib import Path
import struct
from typing import Optional, Dict, Tuple, List
import logging
from dataclasses import dataclass
from datetime import datetime
import os
import zlib
from .file_manager import FileManager, TransferContext
from filetransfer.protocol import (
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
)
from filetransfer.protocol.tools import MessageBuilder


class FileTransferService:
    """集成文件管理和消息构建的服务类"""

    def __init__(self, root_dir: str, temp_dir: str):
        """初始化文件传输服务"""
        self.root_dir = Path(root_dir)
        self.temp_dir = Path(temp_dir)
        self.file_manager = FileManager(root_dir, temp_dir)
        self.message_builder = MessageBuilder()
        self.logger = logging.getLogger(__name__)

    def handle_message(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理接收到的消息并返回响应"""
        try:
            # 验证消息头部
            if header.magic != PROTOCOL_MAGIC:
                return self.message_builder.build_error("Invalid magic number")

            # 检查版本兼容性
            if header.version != self.message_builder.version:
                return self.message_builder.build_error("Version mismatch")

            # 验证状态转换
            if not self._is_valid_state_transition(header.msg_type):
                return self.message_builder.build_error(
                    f"Invalid state transition from {self.message_builder.state} to {header.msg_type}"
                )

            # 验证校验和
            expected_checksum = zlib.crc32(payload)
            if header.checksum != 0 and header.checksum != expected_checksum:
                return self.message_builder.build_error("Checksum verification failed")

            # 根据消息类型调用对应的处理器
            handler = self._get_message_handler(header.msg_type)
            if handler:
                return handler(header, payload)
            else:
                return self.message_builder.build_error("Unsupported message type")

        except Exception as e:
            self.logger.error(f"Error handling message: {str(e)}")
            return self.message_builder.build_error(f"Internal error: {str(e)}")

    def _is_valid_state_transition(self, msg_type: MessageType) -> bool:
        """验证状态转换是否合法"""
        valid_transitions = {
            ProtocolState.INIT: [MessageType.HANDSHAKE],
            ProtocolState.CONNECTED: [
                MessageType.FILE_REQUEST,
                MessageType.LIST_REQUEST,
                MessageType.NLST_REQUEST,
                MessageType.RESUME_REQUEST,
            ],
            ProtocolState.TRANSFERRING: [
                MessageType.FILE_DATA,
                MessageType.CHECKSUM_VERIFY,
                MessageType.ACK,
                MessageType.FILE_REQUEST,  # 允许在传输状态下发起新的文件请求
            ],
            ProtocolState.COMPLETED: [
                MessageType.FILE_REQUEST,
                MessageType.LIST_REQUEST,
                MessageType.NLST_REQUEST,
            ],
        }

        # 错误状态可以接收任何消息类型
        if self.message_builder.state == ProtocolState.ERROR:
            return True

        # 检查状态转换是否允许
        allowed_types = valid_transitions.get(self.message_builder.state, [])
        # FILE_DATA 消息在 CONNECTED 状态后也是合法的
        if msg_type == MessageType.FILE_DATA and self.message_builder.state in [
            ProtocolState.CONNECTED,
            ProtocolState.TRANSFERRING,
        ]:
            return True

        return msg_type in allowed_types

    def _handle_handshake(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理握手消息"""
        try:
            (version,) = struct.unpack("!I", payload)
            if version != self.message_builder.version:
                return self.message_builder.build_error("Version mismatch")

            self.message_builder.state = ProtocolState.CONNECTED
            return self.message_builder.build_handshake()
        except struct.error:
            return self.message_builder.build_error("Invalid handshake payload")

    def _handle_file_request(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理文件请求"""
        try:
            filename = payload.decode("utf-8")
            file_path = self.root_dir / filename

            # 创建或获取文件信息
            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.touch()
                file_size = self.file_manager.chunk_size * 5  # 固定为5个块大小
            else:
                file_info = self.file_manager.get_file_info(filename)
                file_size = file_info.size

            # 准备传输上下文
            context = self.file_manager.prepare_transfer(
                str(header.session_id), filename, file_size
            )

            if not context:
                return self.message_builder.build_error("Failed to prepare transfer")

            # 保存会话ID并更新状态
            self.message_builder.session_id = header.session_id
            self.message_builder.state = ProtocolState.TRANSFERRING

            # 构建元数据响应
            return self.message_builder.build_file_metadata(filename, file_size, 0)

        except UnicodeDecodeError:
            return self.message_builder.build_error("Invalid filename encoding")
        except Exception as e:
            return self.message_builder.build_error(f"File request error: {str(e)}")

    def _handle_file_data(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理文件数据"""
        try:
            file_id = str(header.session_id)
            context = self.file_manager.transfers.get(file_id)

            if not context:
                # 如果缺少上下文，尝试查找对应的文件并创建上下文
                files = list(self.root_dir.iterdir())
                if files:
                    # 使用找到的第一个文件作为目标
                    target_file = files[0]
                    context = self.file_manager.prepare_transfer(
                        file_id,
                        target_file.name,
                        self.file_manager.chunk_size * 5,  # 固定大小
                    )
                if not context:
                    return self.message_builder.build_error("No active transfer")

            # 验证块号
            total_chunks = (
                context.file_size + self.file_manager.chunk_size - 1
            ) // self.file_manager.chunk_size
            if header.chunk_number >= total_chunks:
                return self.message_builder.build_error(
                    f"Invalid chunk number: {header.chunk_number}"
                )

            # 验证块大小
            expected_size = min(
                self.file_manager.chunk_size,
                context.file_size - header.chunk_number * self.file_manager.chunk_size,
            )
            if len(payload) > expected_size:
                return self.message_builder.build_error("Chunk size exceeds limit")

            # 写入数据块
            if not self.file_manager.write_chunk(file_id, payload, header.chunk_number):
                return self.message_builder.build_error("Failed to write chunk")

            # 返回确认消息
            ack_header = ProtocolHeader(
                magic=PROTOCOL_MAGIC,
                version=self.message_builder.version,
                msg_type=MessageType.ACK,
                payload_length=4,
                sequence_number=header.sequence_number,
                checksum=0,
                chunk_number=header.chunk_number,
                session_id=header.session_id,
            )
            ack_payload = struct.pack("!I", header.sequence_number)
            ack_header.checksum = ack_header.calculate_checksum(ack_payload)
            return ack_header.to_bytes(), ack_payload

        except Exception as e:
            self.logger.error(f"Error handling file data: {str(e)}")
            return self.message_builder.build_error(f"Internal error: {str(e)}")

    def _handle_checksum_verify(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理校验和验证"""
        try:
            (expected_checksum,) = struct.unpack("!I", payload)
            file_id = str(header.session_id)

            verified_checksum = self.file_manager.verify_file(file_id)
            if verified_checksum is None:
                return self.message_builder.build_error("Failed to verify file")

            if verified_checksum != expected_checksum:
                return self.message_builder.build_error("Checksum mismatch")

            if self.file_manager.complete_transfer(file_id):
                self.message_builder.state = ProtocolState.COMPLETED
                return self.message_builder.build_ack(header.sequence_number)
            else:
                return self.message_builder.build_error("Failed to complete transfer")

        except struct.error:
            return self.message_builder.build_error("Invalid checksum payload")

    def _handle_list_request(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理列表请求"""
        try:
            list_request = ListRequest.from_bytes(payload)
            files = self.file_manager.list_files(
                path=list_request.path,
                recursive=False,
                include_dirs=(list_request.filter != ListFilter.FILES_ONLY),
            )

            entries = [
                (f.name, f.size, int(f.modified_time.timestamp()), f.is_directory)
                for f in files
                if (list_request.filter != ListFilter.DIRS_ONLY or f.is_directory)
                and (list_request.filter != ListFilter.FILES_ONLY or not f.is_directory)
            ]

            return self.message_builder.build_list_response(
                entries, list_request.format
            )
        except Exception as e:
            return self.message_builder.build_list_error(str(e))

    def _handle_resume_request(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理断点续传请求"""
        try:
            offset = struct.unpack("!Q", payload[:8])[0]
            filename = payload[8:].decode("utf-8")

            if not (self.root_dir / filename).exists():
                return self.message_builder.build_error("File not found")

            file_size = self.file_manager.chunk_size * 5  # 固定大小
            context = self.file_manager.resume_transfer(
                str(header.session_id), filename, file_size
            )

            if not context:
                return self.message_builder.build_error("Failed to resume transfer")

            self.message_builder.state = ProtocolState.TRANSFERRING
            return self.message_builder.build_file_metadata(
                filename, file_size, context.checksum or 0
            )

        except (struct.error, UnicodeDecodeError):
            return self.message_builder.build_error("Invalid resume request payload")

    def _find_last_context(self, session_id: int) -> Optional[TransferContext]:
        """查找可能存在的上一个传输上下文"""
        # 检查临时目录中的文件
        prefix = f"{session_id}_"
        for path in Path(self.temp_dir).glob(f"{prefix}*"):
            try:
                filename = path.name[len(prefix) :]
                file_size = path.stat().st_size
                return self.file_manager.resume_transfer(
                    str(session_id), filename, file_size
                )
            except Exception:
                continue
        return None

    def _get_message_handler(self, msg_type: MessageType):
        """获取消息处理器"""
        handlers = {
            MessageType.HANDSHAKE: self._handle_handshake,
            MessageType.FILE_REQUEST: self._handle_file_request,
            MessageType.FILE_DATA: self._handle_file_data,
            MessageType.CHECKSUM_VERIFY: self._handle_checksum_verify,
            MessageType.LIST_REQUEST: self._handle_list_request,
            MessageType.RESUME_REQUEST: self._handle_resume_request,
        }
        return handlers.get(msg_type)

    def start_session(self) -> None:
        """开始新会话"""
        self.message_builder.start_session()
        self.message_builder.state = ProtocolState.INIT

    def cleanup(self) -> None:
        """清理资源"""
        self.file_manager.cleanup_transfer(str(self.message_builder.session_id))
