import asyncio
from pathlib import Path
import select
import struct
import threading
import time
from typing import Optional, Dict, Tuple, List
import logging
from dataclasses import dataclass
from datetime import datetime
import uuid
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


@dataclass
class SessionInfo:
    """会话信息"""

    service: "FileTransferService"
    created_at: datetime
    last_active: datetime
    client_address: str


class SessionManager:
    """会话管理器，负责为每个客户端维护独立的 FileTransferService 实例"""

    def __init__(self, root_dir: str, temp_dir: str):
        self.root_dir = root_dir
        self.temp_dir = temp_dir
        self._sessions: Dict[str, SessionInfo] = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def create_session(self, client_address: str) -> tuple[str, "FileTransferService"]:
        """创建新的会话"""
        with self._lock:
            # 为每个会话创建独立的临时目录
            session_id = str(uuid.uuid4())
            session_temp_dir = Path(self.temp_dir) / session_id
            session_temp_dir.mkdir(parents=True, exist_ok=True)

            # 创建新的 FileTransferService 实例
            service = FileTransferService(self.root_dir, str(session_temp_dir))
            service.start_session()  # 初始化服务状态

            # 记录会话信息
            now = datetime.now()
            self._sessions[session_id] = SessionInfo(
                service=service,
                created_at=now,
                last_active=now,
                client_address=client_address,
            )

            self.logger.info(
                f"Created new session {session_id} for client {client_address}"
            )
            return session_id, service

    def get_session(self, session_id: str) -> "FileTransferService":
        """获取已存在的会话服务实例"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.last_active = datetime.now()
                return session.service
            return None

    def close_session(self, session_id: str):
        """关闭并清理会话"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions.pop(session_id)
                # 清理会话临时目录
                session_temp_dir = Path(self.temp_dir) / session_id
                try:
                    for file in session_temp_dir.glob("*"):
                        file.unlink()
                    session_temp_dir.rmdir()
                except Exception as e:
                    self.logger.error(f"Error cleaning up session directory: {e}")

                self.logger.info(
                    f"Closed session {session_id} for client {session.client_address}"
                )

    def cleanup_inactive_sessions(self, max_age_minutes: int = 30):
        """清理不活跃的会话"""
        with self._lock:
            now = datetime.now()
            inactive_sessions = [
                session_id
                for session_id, info in self._sessions.items()
                if (now - info.last_active).total_seconds() > max_age_minutes * 60
            ]

            for session_id in inactive_sessions:
                self.close_session(session_id)

    def get_active_sessions_count(self) -> int:
        """获取活跃会话数量"""
        with self._lock:
            return len(self._sessions)


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
                MessageType.HANDSHAKE,
                MessageType.FILE_REQUEST,
                MessageType.LIST_REQUEST,
                MessageType.NLST_REQUEST,
                MessageType.RESUME_REQUEST,
                MessageType.CLOSE,
            ],
            ProtocolState.TRANSFERRING: [
                MessageType.HANDSHAKE,
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
    """基于 ProtocolSocket 的文件传输服务器，支持每个客户端独立会话"""

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
        self.session_manager = SessionManager(root_dir, temp_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.logger = logging.getLogger(__name__)

    def start(self):
        """启动服务器"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.logger.info(f"Server started on {self.server_socket.getsockname()}")

            # 启动会话清理线程
            cleanup_thread = threading.Thread(
                target=self._cleanup_sessions_periodically, daemon=True
            )
            cleanup_thread.start()

            while True:
                client, addr = self.server_socket.accept()
                self.logger.info(f"Accepted connection from {addr}")
                protocol_socket = ProtocolSocket(client, io_mode=self.io_mode)
                self._handle_client(protocol_socket, addr)

        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            self.server_socket.close()

    def _handle_client(self, protocol_socket: ProtocolSocket, client_addr: tuple):
        """处理客户端连接"""
        session_id = None
        try:
            # 为新客户端创建会话
            session_id, service = self.session_manager.create_session(
                f"{client_addr[0]}:{client_addr[1]}"
            )

            while True:
                try:
                    header, payload = protocol_socket.receive_message()
                except ConnectionError:
                    self.logger.info("Client disconnected")
                    break

                # 使用会话特定的服务处理消息
                response_header_bytes, response_payload = service.handle_message(
                    header, payload
                )

                protocol_socket.send_message(response_header_bytes, response_payload)

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            if session_id:
                self.session_manager.close_session(session_id)
            protocol_socket.close()

    def _cleanup_sessions_periodically(self, interval_minutes: int = 5):
        """定期清理不活跃的会话"""
        while True:
            time.sleep(interval_minutes * 60)
            self.session_manager.cleanup_inactive_sessions()


class AsyncProtocolServer:
    """异步版本的协议服务器，支持每个客户端独立会话"""

    def __init__(self, host: str, port: int, root_dir: str, temp_dir: str):
        self.host = host
        self.port = port
        self.session_manager = SessionManager(root_dir, temp_dir)
        self.logger = logging.getLogger(__name__)

    async def start(self):
        """启动异步服务器"""
        server = await asyncio.start_server(self._handle_client, self.host, self.port)

        # 启动会话清理任务
        asyncio.create_task(self._cleanup_sessions_periodically())

        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader, writer):
        """处理异步客户端连接"""
        session_id = None
        protocol_socket = ProtocolSocket(None, io_mode=IOMode.ASYNC)
        protocol_socket.connected = True
        protocol_socket.reader = reader
        protocol_socket.writer = writer

        try:
            # 获取客户端地址
            client_addr = writer.get_extra_info("peername")
            # 创建新会话
            session_id, service = self.session_manager.create_session(
                f"{client_addr[0]}:{client_addr[1]}"
            )

            while True:
                try:
                    header, payload = await protocol_socket.async_receive_message()
                except ConnectionError:
                    break

                response_header, response_payload = service.handle_message(
                    header, payload
                )

                await protocol_socket.async_send_message(
                    response_header, response_payload
                )

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            if session_id:
                self.session_manager.close_session(session_id)
            writer.close()
            await writer.wait_closed()

    async def _cleanup_sessions_periodically(self, interval_minutes: int = 5):
        """定期清理不活跃的会话"""
        while True:
            await asyncio.sleep(interval_minutes * 60)
            self.session_manager.cleanup_inactive_sessions()


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
        self.service = FileTransferService(root_dir, temp_dir)
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
            response_header, response_payload = self.service.handle_message(
                header, payload
            )

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
        # 关闭所有客户端连接
        client_sockets = list(self.clients.keys())  # 创建副本避免修改字典时的迭代错误
        for client_socket in client_sockets:
            try:
                self._handle_client_error(client_socket, [], [])
            except:
                pass  # 忽略关闭过程中的错误

        # 关闭服务器socket
        try:
            if hasattr(self, "server_socket"):
                self.server_socket.shutdown(socket.SHUT_RDWR)
                self.server_socket.close()
        except:
            pass  # 忽略关闭过程中的错误


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
        self._shutdown_flag = False  # 初始化标志
        self._active_clients = set()  # 跟踪活动的客户端连接
        self._clients_lock = threading.Lock()

    def stop(self):
        """优雅地停止服务器"""
        self._shutdown_flag = True

        # 关闭所有活动的客户端连接
        with self._clients_lock:
            for client_socket in list(self._active_clients):  # 使用列表副本遍历
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                    client_socket.close()
                except:
                    pass  # 忽略关闭过程中的错误
            self._active_clients.clear()

        # 关闭服务器socket
        try:
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except:
            pass  # 忽略关闭过程中的错误

        try:
            self.server_socket.close()
        except:
            pass

    def _handle_client(self, client_socket):
        """处理客户端连接"""
        try:
            # 添加到活动客户端集合
            with self._clients_lock:
                self._active_clients.add(client_socket)

            protocol_socket = ProtocolSocket(client_socket, io_mode=self.io_mode)

            while not self._shutdown_flag:
                try:
                    header, payload = protocol_socket.receive_message()
                    if not header:  # 检查连接是否已关闭
                        break

                    response_header, response_payload = self.service.handle_message(
                        header, payload
                    )

                    if not protocol_socket.send_message(
                        response_header, response_payload
                    ):
                        break  # 发送失败表示连接已关闭

                except (ConnectionError, socket.error):
                    break  # 任何连接错误都中断循环

        except Exception as e:
            self.logger.error(f"Error handling client: {e}")
        finally:
            # 从活动客户端集合中移除
            with self._clients_lock:
                self._active_clients.discard(client_socket)  # 使用discard避免KeyError
            try:
                client_socket.close()
            except:
                pass

    def start(self):
        """启动服务器"""
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.logger.info(f"Server started on {self.server_socket.getsockname()}")

            while not self._shutdown_flag:
                try:
                    self.server_socket.settimeout(
                        1.0
                    )  # 设置超时，以便定期检查shutdown标志
                    try:
                        client, addr = self.server_socket.accept()
                        self.logger.info(f"Accepted connection from {addr}")
                        client_thread = threading.Thread(
                            target=self._handle_client, args=(client,)
                        )
                        client_thread.daemon = True
                        client_thread.start()
                    except socket.timeout:
                        continue  # 超时后检查shutdown标志
                    except socket.error as e:
                        if self._shutdown_flag:
                            break
                        self.logger.error(f"Accept error: {e}")

                except Exception as e:
                    if self._shutdown_flag:
                        break
                    self.logger.error(f"Server loop error: {e}")

        except Exception as e:
            if not self._shutdown_flag:  # 只在非正常关闭时记录错误
                self.logger.error(f"Server error: {e}")
        finally:
            self.stop()  # 确保所有资源都被清理


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
