import os
import socket
import logging
import threading
from pathlib import Path
from typing import Optional

from filetransfer.protocol import (
    MessageType,
    ProtocolHeader,
    ListRequest,
    ListFilter,
    ListResponseFormat,
    PROTOCOL_MAGIC,
)
from filetransfer.network import ProtocolSocket, IOMode
from .transfer import FileTransferService
from .utils import TransferUtils


class FileDownloadServer:
    """
    文件下载服务器
    基于已有的 FileTransferService 和 TransferUtils 实现
    """

    def __init__(
        self,
        root_dir: str,
        temp_dir: Optional[str] = None,
        host: str = "localhost",
        port: int = 9999,
        chunk_size: int = 8192,
    ):
        """
        初始化文件下载服务器

        Args:
            root_dir: 文件根目录
            temp_dir: 临时目录（可选）
            host: 服务器监听地址
            port: 服务器监听端口
            chunk_size: 文件传输块大小
        """
        # 目录配置
        self.root_dir = Path(root_dir)
        self.temp_dir = Path(temp_dir or os.path.join(root_dir, "_temp"))

        # 确保目录存在
        os.makedirs(self.root_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        # 网络配置
        self.host = host
        self.port = port

        # 创建文件传输服务
        self.file_service = FileTransferService(
            root_dir=str(self.root_dir), temp_dir=str(self.temp_dir)
        )

        # 创建传输工具
        self.transfer_utils = TransferUtils(
            service=self.file_service, chunk_size=chunk_size
        )

        # 日志配置
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger(self.__class__.__name__)

        # 服务器套接字
        self.server_socket = None
        self.running = False

    def start(self):
        """
        启动文件下载服务器
        """
        # 创建服务器套接字
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)

        self.running = True
        self.logger.info(f"文件下载服务器启动，监听 {self.host}:{self.port}")

        try:
            while self.running:
                try:
                    # 接受客户端连接
                    client_socket, client_address = self.server_socket.accept()
                    self.logger.info(f"收到来自 {client_address} 的连接")

                    # 为每个客户端创建单独的线程处理
                    client_thread = threading.Thread(
                        target=self._handle_client, args=(client_socket, client_address)
                    )
                    client_thread.start()

                except socket.error as e:
                    if not self.running:
                        break
                    self.logger.error(f"接受连接时发生错误: {e}")

        except KeyboardInterrupt:
            self.logger.info("服务器正在关闭...")
        finally:
            self.stop()

    def stop(self):
        """
        停止服务器
        """
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        self.logger.info("文件下载服务器已停止")

    def _handle_client(self, client_socket: socket.socket, client_address: tuple):
        """
        处理单个客户端的请求

        Args:
            client_socket: 客户端套接字
            client_address: 客户端地址
        """
        # 创建协议套接字
        protocol_socket = ProtocolSocket(client_socket, io_mode=IOMode.SINGLE)

        try:
            while True:
                try:
                    # 接收消息
                    header, payload = protocol_socket.receive_message()

                    # 处理不同类型的消息
                    if header.msg_type == MessageType.LIST_REQUEST:
                        # 处理文件列表请求
                        self._handle_list_request(protocol_socket, header, payload)
                    elif header.msg_type == MessageType.FILE_REQUEST:
                        # 处理文件下载请求
                        self._handle_file_request(protocol_socket, header, payload)
                    else:
                        # 不支持的消息类型
                        self._send_error(protocol_socket, "不支持的消息类型")

                except ConnectionError:
                    self.logger.info(f"客户端 {client_address} 断开连接")
                    break
                except Exception as e:
                    self.logger.error(
                        f"处理客户端 {client_address} 消息时发生错误: {e}"
                    )
                    break

        except Exception as e:
            self.logger.error(f"处理客户端 {client_address} 时发生异常: {e}")
        finally:
            # 关闭客户端连接
            protocol_socket.close()

    def _handle_list_request(
        self, protocol_socket: ProtocolSocket, header: ProtocolHeader, payload: bytes
    ):
        """
        处理文件列表请求

        Args:
            protocol_socket: 协议套接字
            header: 消息头
            payload: 请求载荷
        """
        try:
            # 解析文件列表请求
            list_request = ListRequest.from_bytes(payload)

            # 准备响应
            response_header_bytes, response_payload = self.file_service.handle_message(
                header, payload
            )

            # 发送响应
            response_header = ProtocolHeader.from_bytes(response_header_bytes)
            protocol_socket.send_message(response_header.msg_type, response_payload)

        except Exception as e:
            self.logger.error(f"处理文件列表请求失败: {e}")
            self._send_error(protocol_socket, f"文件列表请求失败: {e}")

    def _handle_file_request(
        self, protocol_socket: ProtocolSocket, header: ProtocolHeader, payload: bytes
    ):
        """
        处理文件下载请求

        Args:
            protocol_socket: 协议套接字
            header: 消息头
            payload: 请求载荷
        """
        try:
            # 准备响应
            response_header_bytes, response_payload = self.file_service.handle_message(
                header, payload
            )
            response_header = ProtocolHeader.from_bytes(response_header_bytes)

            # 发送文件元数据
            protocol_socket.send_message(response_header.msg_type, response_payload)

            # 如果元数据发送成功，开始文件传输
            if response_header.msg_type != MessageType.ERROR:
                # 如何传输文件取决于 FileTransferService 的实现
                # 可能已在 handle_message 中处理了文件传输
                pass

        except Exception as e:
            self.logger.error(f"处理文件下载请求失败: {e}")
            self._send_error(protocol_socket, f"文件下载请求失败: {e}")

    def _send_error(self, protocol_socket: ProtocolSocket, error_message: str):
        """
        发送错误消息

        Args:
            protocol_socket: 协议套接字
            error_message: 错误消息
        """
        try:
            # 创建错误消息头和载荷
            error_payload = error_message.encode("utf-8")
            error_header = ProtocolHeader(
                magic=PROTOCOL_MAGIC,
                version=1,
                msg_type=MessageType.ERROR,
                payload_length=len(error_payload),
                sequence_number=1,
                checksum=0,
                chunk_number=0,
                session_id=1,
            )

            # 发送错误消息
            protocol_socket.send_message(MessageType.ERROR, error_payload)
        except Exception as e:
            self.logger.error(f"发送错误消息失败: {e}")


def main():
    """
    服务器启动入口
    """
    # 创建并启动文件下载服务器
    server = FileDownloadServer(
        root_dir="/path/to/shared/files",  # 替换为实际的共享文件目录
        host="localhost",
        port=9999,
    )

    # 启动服务器
    server.start()


if __name__ == "__main__":
    main()
