import asyncio
from pathlib import Path
import select
import struct
import threading
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
import socket
from filetransfer.network import ProtocolSocket, IOMode


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
                MessageType.RESUME_REQUEST,  # 允许在传输状态下发起断点续传请求
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
            self.logger.debug(f"Parsed list request: {list_request}")

            files = self.file_manager.list_files(
                path=list_request.path,
                recursive=False,
                include_dirs=(list_request.filter != ListFilter.FILES_ONLY),
            )
            self.logger.debug(f"Found {len(files)} files")

            entries = [
                (f.name, f.size, int(f.modified_time.timestamp()), f.is_directory)
                for f in files
                if (list_request.filter != ListFilter.DIRS_ONLY or f.is_directory)
                and (list_request.filter != ListFilter.FILES_ONLY or not f.is_directory)
            ]
            self.logger.debug(f"Filtered to {len(entries)} entries")

            return self.message_builder.build_list_response(
                entries, list_request.format
            )
        except Exception as e:
            self.logger.error(f"Error handling list request: {str(e)}")
            return self.message_builder.build_list_error(str(e))

    def _handle_file_request(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理文件请求"""
        try:
            filename = payload.decode("utf-8")
            file_path = self.root_dir / filename

            # 获取或创建文件
            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.touch()

            # 获取实际文件大小
            file_size = file_path.stat().st_size

            # 准备传输上下文
            context = self.file_manager.prepare_transfer(
                str(header.session_id), filename, file_size
            )
            if not context:
                return self.message_builder.build_error("Failed to prepare transfer")

            # 更新状态
            self.message_builder.session_id = header.session_id
            self.message_builder.state = ProtocolState.TRANSFERRING

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
                return self.message_builder.build_error("No active transfer")

            # 验证块号
            total_chunks = max(
                1,
                (context.file_size + self.file_manager.chunk_size - 1)
                // self.file_manager.chunk_size,
            )
            if header.chunk_number >= total_chunks:
                return self.message_builder.build_error(
                    f"Invalid chunk number: {header.chunk_number}"
                )

            # 验证块大小
            expected_size = (
                min(
                    self.file_manager.chunk_size,
                    context.file_size
                    - header.chunk_number * self.file_manager.chunk_size,
                )
                if context.file_size > 0
                else self.file_manager.chunk_size
            )
            if len(payload) > expected_size:
                return self.message_builder.build_error("Chunk size exceeds limit")

            # 写入数据块
            if not self.file_manager.write_chunk(file_id, payload, header.chunk_number):
                return self.message_builder.build_error("Failed to write chunk")

            # 返回分块确认消息
            return self.message_builder.build_chunk_ack(
                header.sequence_number, header.chunk_number
            )

        except Exception as e:
            self.logger.error(f"Error handling file data: {str(e)}")
            return self.message_builder.build_error(f"Internal error: {str(e)}")

    def _handle_resume_request(
        self, header: ProtocolHeader, payload: bytes
    ) -> Tuple[bytes, bytes]:
        """处理断点续传请求"""
        try:
            offset = struct.unpack("!Q", payload[:8])[0]
            filename = payload[8:].decode("utf-8")

            file_path = self.root_dir / filename
            if not file_path.exists():
                return self.message_builder.build_error("File not found")

            # 获取实际文件大小
            file_size = file_path.stat().st_size

            # 验证偏移量
            if offset > file_size:
                return self.message_builder.build_error("Invalid offset")

            # 准备传输上下文
            context = self.file_manager.prepare_transfer(
                str(header.session_id), filename, file_size
            )
            if not context:
                return self.message_builder.build_error("Failed to prepare transfer")

            # 更新状态
            self.message_builder.session_id = header.session_id
            self.message_builder.state = ProtocolState.TRANSFERRING

            return self.message_builder.build_file_metadata(
                filename, file_size, context.checksum or 0
            )

        except (struct.error, UnicodeDecodeError):
            return self.message_builder.build_error("Invalid resume request payload")
        except Exception as e:
            return self.message_builder.build_error(f"Resume error: {str(e)}")

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


class ProtocolServer:
    """基于 ProtocolSocket 的文件传输服务器"""

    def __init__(
        self,
        host: str,
        port: int,
        root_dir: str,
        temp_dir: str,
        io_mode: IOMode = IOMode.SINGLE,
    ):
        self.host = host
        self.port = port
        self.io_mode = io_mode
        self.service = FileTransferService(root_dir, temp_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logger = logging.getLogger(__name__)

    def start(self):
        """启动服务器"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.logger.info(f"Server started on {self.server_socket.getsockname()}")

            while True:
                client, addr = self.server_socket.accept()
                self.logger.info(f"Accepted connection from {addr}")
                protocol_socket = ProtocolSocket(client, io_mode=self.io_mode)
                self._handle_client(protocol_socket)

        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            self.server_socket.close()

    def _handle_client(self, protocol_socket: ProtocolSocket):
        """处理客户端连接"""
        try:
            while True:
                try:
                    # ProtocolSocket只负责最基础的收发
                    header, payload = protocol_socket.receive_message()
                except ConnectionError:
                    self.logger.info("Client disconnected")
                    break

                # FileTransferService负责消息的处理和响应构建
                response_header_bytes, response_payload = self.service.handle_message(
                    header, payload
                )

                # ProtocolSocket只负责发送字节
                protocol_socket.send_message(response_header_bytes, response_payload)

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            protocol_socket.close()


class AsyncProtocolServer:
    """异步版本的协议服务器"""

    def __init__(self, host: str, port: int, root_dir: str, temp_dir: str):
        self.host = host
        self.service = FileTransferService(root_dir, temp_dir)
        self.port = port
        self.logger = logging.getLogger(__name__)

    async def start(self):
        """启动异步服务器"""
        server = await asyncio.start_server(self._handle_client, self.host, self.port)

        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader, writer):
        """处理异步客户端连接"""
        protocol_socket = ProtocolSocket(None, io_mode=IOMode.ASYNC)
        protocol_socket.connected = True
        protocol_socket.reader = reader
        protocol_socket.writer = writer
        try:
            while True:
                try:
                    header, payload = await protocol_socket.async_receive_message()
                except ConnectionError:
                    break

                response_header, response_payload = self.service.handle_message(
                    header, payload
                )

                await protocol_socket.async_send_message(
                    response_header, response_payload
                )

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            writer.close()
            await writer.wait_closed()


class SelectServer:
    """基于多线程和 select 架构的文件传输服务器"""

    def __init__(
        self,
        host: str,
        port: int,
        root_dir: str,
        temp_dir: str,
        io_mode: IOMode = IOMode.SINGLE,
    ):
        self.host = host
        self.port = port
        self.io_mode = io_mode
        self.root_dir = root_dir
        self.temp_dir = temp_dir
        self.file_manager = FileManager(root_dir, temp_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setblocking(False)
        self.logger = logging.getLogger(__name__)
        self.clients = {}  # 存储所有已连接客户端的协议套接字
        self._shutdown_flag = False

    def start(self):
        """启动服务器"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.setblocking(False)
            self.logger.info(f"Server started on {self.server_socket.getsockname()}")

            # 初始化 select 监听列表
            inputs = [self.server_socket]
            outputs = []
            while not self._shutdown_flag:
                # 使用 select 来监听所有活跃的 socket 连接
                readable, writable, exceptional = select.select(
                    inputs, outputs, inputs, 0.1
                )

                for s in readable:
                    if s is self.server_socket:
                        # 接受新连接
                        self._accept_connection(inputs)
                    else:
                        # 处理已连接的客户端数据
                        self._handle_client_message(s, inputs, outputs)

                # 可写的 socket 会被处理（例如异步响应）
                for s in writable:
                    pass  # 可根据需要添加对输出的处理

                # 错误的 socket（通常是客户端断开连接）
                for s in exceptional:
                    self._handle_client_error(s, inputs, outputs)

        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            self.server_socket.close()

    def _accept_connection(self, inputs):
        """接受新连接并将其添加到输入列表"""
        client_socket, addr = self.server_socket.accept()
        self.logger.info(f"Accepted connection from {addr}")
        client_socket.setblocking(False)
        inputs.append(client_socket)
        protocol_socket = ProtocolSocket(client_socket, io_mode=self.io_mode)
        self.clients[client_socket] = protocol_socket

    def _handle_client_message(self, client_socket, inputs, outputs):
        """处理客户端消息"""
        protocol_socket = self.clients.get(client_socket)
        if protocol_socket is None:
            return

        try:
            # 接收消息
            header, payload = protocol_socket.receive_message()

            # 使用文件管理服务处理消息
            response_header, response_payload = self._process_message(header, payload)

            # 发送响应
            protocol_socket.send_message(response_header, response_payload)

        except ConnectionError:
            self.logger.info("Client disconnected")
            self._handle_client_error(client_socket, inputs, outputs)

    def _handle_client_error(self, client_socket, inputs, outputs):
        """处理客户端断开连接的错误"""
        if client_socket in inputs:
            inputs.remove(client_socket)
        if client_socket in outputs:
            outputs.remove(client_socket)
        protocol_socket = self.clients.pop(client_socket, None)
        if protocol_socket:
            protocol_socket.close()
        client_socket.close()

    def _process_message(self, header: ProtocolHeader, payload: bytes) -> tuple:
        """处理消息并生成响应"""
        # 假设有一个MessageBuilder负责消息构建
        message_builder = MessageBuilder()
        if header.msg_type == MessageType.HANDSHAKE:
            return message_builder.build_handshake()
        # 处理其他消息类型
        return message_builder.build_error("Unknown message type")

    def stop(self):
        """优雅地停止服务器"""
        self._shutdown_flag = True
        for client_socket in self.clients:
            client_socket.close()
        self.server_socket.close()


class ThreadedServer:
    """基于多线程的文件传输服务器"""

    def __init__(
        self,
        host: str,
        port: int,
        root_dir: str,
        temp_dir: str,
        io_mode: IOMode = IOMode.SINGLE,
    ):
        self.host = host
        self.port = port
        self.io_mode = io_mode
        self.root_dir = root_dir
        self.temp_dir = temp_dir
        self.file_manager = FileManager(root_dir, temp_dir)
        self.service = FileTransferService(root_dir, temp_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logger = logging.getLogger(__name__)

    def start(self):
        """启动服务器"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.logger.info(f"Server started on {self.server_socket.getsockname()}")

            while True:
                client, addr = self.server_socket.accept()
                self.logger.info(f"Accepted connection from {addr}")
                # 启动一个新线程处理客户端
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client,)
                )
                client_thread.daemon = True
                client_thread.start()

        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            self.server_socket.close()

    def _handle_client(self, client_socket):
        """处理客户端连接"""
        try:
            protocol_socket = ProtocolSocket(client_socket, io_mode=self.io_mode)

            while True:
                try:
                    header, payload = protocol_socket.receive_message()

                    # 使用文件管理服务处理消息
                    response_header, response_payload = self.service.handle_message(
                        header, payload
                    )

                    # 发送响应
                    protocol_socket.send_message(response_header, response_payload)

                except ConnectionError:
                    self.logger.info("Client disconnected")
                    break

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            client_socket.close()

    def _process_message(self, header: ProtocolHeader, payload: bytes) -> tuple:
        """处理消息并生成响应"""
        # 假设有一个MessageBuilder负责消息构建
        message_builder = MessageBuilder()
        if header.msg_type == MessageType.HANDSHAKE:
            return message_builder.build_handshake()
        # 处理其他消息类型
        return message_builder.build_error("Unknown message type")


# 使用示例
"""
# 同步服务器
server = ProtocolServer(
    host="localhost",
    port=8000,
    root_dir="/path/to/files",
    temp_dir="/path/to/temp",
    io_mode=IOMode.SINGLE  # 或 THREADED, NONBLOCKING
)
server.start()

# 异步服务器
async_server = AsyncProtocolServer(
    host="localhost",
    port=8000,
    root_dir="/path/to/files",
    temp_dir="/path/to/temp"
)
asyncio.run(async_server.start())
"""
