import select
import socket
from .base import BaseProtocolHandler
from filetransfer.protocol import ProtocolHeader, ProtocolState
from filetransfer.network import ProtocolSocket, IOMode


class NonblockingProtocolHandler(BaseProtocolHandler):
    """非阻塞模式处理器(使用select)"""

    def __init__(self):
        super().__init__()
        self.socket_map = {}  # 存储socket和对应的处理状态
        self.listening_sockets = set()  # 监听socket集合
        self.read_sockets = set()  # 需要监听读事件的socket集合
        self.write_sockets = set()  # 需要监听写事件的socket集合
        self.pending_connections = set()  # 等待连接完成的socket集合

    def _is_server_socket(self, sock):
        """检查是否为服务器socket"""
        if not sock.socket:
            return False

        # 检查是否为SOCK_STREAM类型且已绑定地址
        try:
            sock_type = sock.socket.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            if sock_type != socket.SOCK_STREAM:
                return False

            # 尝试获取socket的本地地址
            address = sock.socket.getsockname()
            if not address:
                return False

            # 尝试获取peer地址，如果能获取说明是已连接的客户端socket
            try:
                sock.socket.getpeername()
                return False
            except socket.error:
                # 不能获取peer地址，并且其他检查都通过，说明可能是监听socket
                pass

            return True

        except socket.error:
            return False

    def add_socket(self, sock: ProtocolSocket):
        """添加要监听的socket"""
        fd = sock.fileno()
        self.socket_map[fd] = {"socket": sock, "state": ProtocolState.INIT}

        # 检查是否为服务器socket
        if self._is_server_socket(sock):
            self.listening_sockets.add(fd)
            self.read_sockets.add(fd)
            self.logger.debug(f"Added server socket {fd}")
            try:
                addr = sock.socket.getsockname()
                self.logger.debug(f"Server socket {fd} bound to {addr}")
            except socket.error:
                pass
        else:
            self.read_sockets.add(fd)
            self.write_sockets.add(fd)
            self.pending_connections.add(fd)
            self.logger.debug(f"Added client socket {fd}")
            try:
                addr = sock.socket.getpeername()
                self.logger.debug(f"Client socket {fd} connected to {addr}")
            except socket.error:
                pass

    def remove_socket(self, sock: ProtocolSocket):
        """移除socket"""
        fd = sock.fileno()
        if fd in self.socket_map:
            self.logger.debug(f"Removing socket {fd}")
            self.listening_sockets.discard(fd)
            self.read_sockets.discard(fd)
            self.write_sockets.discard(fd)
            self.pending_connections.discard(fd)
            del self.socket_map[fd]

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """分发消息到具体的处理函数"""
        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
                self.logger.debug(
                    f"Message dispatched to handler: type={header.msg_type}"
                )
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def handle_events(self, timeout: float = 1.0):
        """使用select监听socket事件"""
        if not self.socket_map:
            return

        self.logger.debug(f"开始select，当前有 {len(self.socket_map)} 个socket")
        self.logger.debug(f"监听socket列表: {self.listening_sockets}")
        self.logger.debug(f"读socket列表: {self.read_sockets}")
        self.logger.debug(f"写socket列表: {self.write_sockets}")
        self.logger.debug(f"待连接socket列表: {self.pending_connections}")

        try:
            readable, writable, exceptional = select.select(
                self.read_sockets,
                self.write_sockets,
                self.read_sockets | self.write_sockets,
                timeout,
            )

            # 处理异常的socket
            for sock_fd in exceptional:
                sock_info = self.socket_map.get(sock_fd)
                if sock_info:
                    self.logger.debug(f"Socket {sock_fd} encountered an error")
                    self.remove_socket(sock_info["socket"])

            # 处理可写的socket（用于检查连接状态）
            for sock_fd in writable:
                if sock_fd in self.pending_connections:
                    sock_info = self.socket_map.get(sock_fd)
                    if sock_info and sock_info["socket"].check_connection():
                        self.pending_connections.discard(sock_fd)
                        self.write_sockets.discard(sock_fd)  # 连接完成后不再监听写事件
                        self.logger.debug(f"Client socket {sock_fd} connected")

            # 处理可读的socket
            for sock_fd in readable:
                sock_info = self.socket_map.get(sock_fd)
                if not sock_info:
                    continue

                sock = sock_info["socket"]

                # 处理监听socket上的新连接
                if sock_fd in self.listening_sockets:
                    try:
                        client_sock, addr = sock.socket.accept()
                        self.logger.debug(f"接受新连接: {addr}")
                        # 设置非阻塞模式
                        client_sock.setblocking(False)
                        # 创建新的ProtocolSocket并添加
                        client_protocol = ProtocolSocket(
                            client_sock, io_mode=IOMode.NONBLOCKING
                        )
                        self.add_socket(client_protocol)
                    except Exception as e:
                        self.logger.error(f"Accept error: {e}")
                    continue

                # 处理普通socket的数据
                try:
                    header, payload = sock.receive_message()
                    self.logger.debug(f"收到消息: type={header.msg_type}")
                    self.handle_message(header, payload)
                except ConnectionError as e:
                    self.logger.error(f"Connection error: {e}")
                    self.remove_socket(sock)
                except Exception as e:
                    self.logger.error(f"Socket error: {e}")
                    self.remove_socket(sock)

        except Exception as e:
            self.logger.error(f"Select error: {e}")
