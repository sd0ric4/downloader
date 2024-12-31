import unittest
import socket
import logging
from filetransfer.protocol import (
    ListFilter,
    ListRequest,
    ListResponseFormat,
    ProtocolHeader,
    MessageType,
    ProtocolState,
    ProtocolVersion,
    PROTOCOL_MAGIC,
)
from filetransfer.network import ProtocolSocket
from filetransfer.handler import (
    create_protocol_handler,
    IOMode,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestSocket:
    """测试用的协议Socket包装"""

    def __init__(self, socket, handler):
        self.socket = socket
        self.handler = handler
        self.protocol_socket = ProtocolSocket(socket, IOMode.SINGLE)

    def send_message(self, msg_type: MessageType, payload: bytes):
        """发送消息"""
        return self.protocol_socket.send_message(msg_type, payload)

    def receive_message(self):
        """接收消息"""
        return self.protocol_socket.receive_message()


class TestSingleThreadedProtocolHandler(unittest.TestCase):
    """单线程协议处理器的单元测试"""

    def setUp(self):
        """每个测试用例前的设置"""
        self.handler = create_protocol_handler(IOMode.SINGLE)
        self.responses = {}
        self.setup_handler()

    def setup_handler(self):
        """配置协议处理器"""

        def handle_handshake(header: ProtocolHeader, payload: bytes) -> bool:
            """处理握手消息"""
            logger.info("Handling handshake message")
            version = int.from_bytes(payload, "big")
            if version != self.handler.protocol_version:
                logger.error(
                    f"Protocol version mismatch: expected {self.handler.protocol_version}, got {version}"
                )
                return False

            self.handler.state = ProtocolState.CONNECTED
            logger.info("Handshake successful")

            # 在这里设置响应消息
            self.responses[header.msg_type] = (MessageType.ACK, b"OK")
            return True

        def handle_close(header: ProtocolHeader, payload: bytes) -> bool:
            """处理关闭消息"""
            logger.info("Handling close message")
            self.handler.state = ProtocolState.COMPLETED
            self.responses[header.msg_type] = (MessageType.ACK, b"CLOSING")
            return True

        def handle_error(header: ProtocolHeader, payload: bytes) -> bool:
            """处理错误消息"""
            logger.info("Handling error message")
            return False

        def handle_file_request(header: ProtocolHeader, payload: bytes) -> None:
            # 先设置响应
            self.responses[header.msg_type] = (MessageType.ACK, b"FILE_REQUEST_OK")
            if not self.handler.check_state(ProtocolState.CONNECTED):
                self.handler.state = ProtocolState.ERROR
                return
            self.handler.state = ProtocolState.TRANSFERRING

        # 注册消息处理器
        self.handler.register_handler(MessageType.HANDSHAKE, handle_handshake)
        self.handler.register_handler(MessageType.CLOSE, handle_close)
        self.handler.register_handler(MessageType.ERROR, handle_error)
        # 注册文件请求处理器
        self.handler.register_handler(MessageType.FILE_REQUEST, handle_file_request)

    def test_handshake_success(self):
        """测试成功的握手过程"""
        # 创建一对connected sockets用于测试
        server_sock, client_sock = socket.socketpair()
        try:
            # 包装socket
            test_socket = TestSocket(server_sock, self.handler)
            client = TestSocket(client_sock, self.handler)

            # 客户端发送握手消息
            handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
            header = client.send_message(MessageType.HANDSHAKE, handshake_payload)

            # 服务端接收并处理消息
            msg_header, msg_payload = test_socket.receive_message()
            self.handler.handle_message(msg_header, msg_payload)

            # 服务端发送响应(从handler获取响应)
            response_type, response_payload = self.responses[msg_header.msg_type]
            test_socket.send_message(response_type, response_payload)

            # 客户端接收响应
            resp_header, resp_payload = client.receive_message()

            # 验证响应
            self.assertEqual(resp_header.msg_type, MessageType.ACK)
            self.assertEqual(resp_payload, b"OK")
            self.assertEqual(self.handler.state, ProtocolState.CONNECTED)

            # 发送关闭消息
            header = client.send_message(MessageType.CLOSE, b"")
            msg_header, msg_payload = test_socket.receive_message()
            self.handler.handle_message(msg_header, msg_payload)

            # 发送关闭响应
            response_type, response_payload = self.responses[msg_header.msg_type]
            test_socket.send_message(response_type, response_payload)

            # 接收关闭确认
            resp_header, resp_payload = client.receive_message()
            self.assertEqual(resp_header.msg_type, MessageType.ACK)
            self.assertEqual(resp_payload, b"CLOSING")
            self.assertEqual(self.handler.state, ProtocolState.COMPLETED)

        finally:
            server_sock.close()
            client_sock.close()

    def test_invalid_version(self):
        """测试无效的协议版本"""
        server_sock, client_sock = socket.socketpair()
        try:
            test_socket = TestSocket(server_sock, self.handler)
            client = TestSocket(client_sock, self.handler)

            # 发送错误版本的握手消息
            invalid_version = 99
            handshake_payload = invalid_version.to_bytes(4, "big")
            header = client.send_message(MessageType.HANDSHAKE, handshake_payload)

            # 服务端接收并处理消息
            msg_header, msg_payload = test_socket.receive_message()
            self.handler.handle_message(msg_header, msg_payload)

            # 验证处理器状态
            self.assertEqual(self.handler.state, ProtocolState.INIT)

        finally:
            server_sock.close()
            client_sock.close()

    def test_state_transition(self):
        """测试状态转换"""
        # 初始状态检查
        self.assertEqual(self.handler.state, ProtocolState.INIT)

        # 执行握手测试会完成整个状态转换流程
        self.test_handshake_success()

        # 验证最终状态
        self.assertEqual(self.handler.state, ProtocolState.COMPLETED)


class TestSingleThreadedProtocolHandlerExtended(unittest.TestCase):
    def setUp(self):
        self.handler = create_protocol_handler(IOMode.SINGLE)
        self.responses = {}
        self.setup_handler()
        self.server_sock, self.client_sock = socket.socketpair()
        self.test_socket = TestSocket(self.server_sock, self.handler)
        self.client = TestSocket(self.client_sock, self.handler)

    def tearDown(self):
        self.server_sock.close()
        self.client_sock.close()

    def setup_handler(self):
        """设置协议处理器和对应的处理函数"""

        def handle_handshake(header: ProtocolHeader, payload: bytes) -> None:
            version = int.from_bytes(payload, "big")
            # 先设置响应
            self.responses[header.msg_type] = (MessageType.ACK, b"OK")
            if version != self.handler.protocol_version:
                self.handler.state = ProtocolState.ERROR
                return
            self.handler.state = ProtocolState.CONNECTED

        def handle_file_request(header: ProtocolHeader, payload: bytes) -> None:
            # 先设置响应
            self.responses[header.msg_type] = (MessageType.ACK, b"FILE_REQUEST_OK")
            if not self.handler.check_state(ProtocolState.CONNECTED):
                self.handler.state = ProtocolState.ERROR
                return
            self.handler.state = ProtocolState.TRANSFERRING

        def handle_file_data(header: ProtocolHeader, payload: bytes) -> None:
            # 先设置响应
            self.responses[header.msg_type] = (MessageType.FILE_DATA, b"DATA_RECEIVED")
            if not self.handler.check_state(ProtocolState.TRANSFERRING):
                self.handler.state = ProtocolState.ERROR
                return

        def handle_close(header: ProtocolHeader, payload: bytes) -> None:
            # 先设置响应
            self.responses[header.msg_type] = (MessageType.ACK, b"CLOSING")
            if not self.handler.check_state(
                ProtocolState.CONNECTED
            ) and not self.handler.check_state(ProtocolState.TRANSFERRING):
                self.handler.state = ProtocolState.ERROR
                return
            self.handler.state = ProtocolState.COMPLETED

        def handle_error(header: ProtocolHeader, payload: bytes) -> None:
            self.handler.state = ProtocolState.ERROR

        def handle_list_request(header: ProtocolHeader, payload: bytes) -> bool:
            """处理LIST请求"""
            logger.info("Handling LIST request")
            if not self.handler.check_state(ProtocolState.CONNECTED):
                self.handler.state = ProtocolState.ERROR
                return False

            try:
                # 解析列表请求
                list_request = ListRequest.from_bytes(payload)

                # 根据格式类型返回不同的响应
                if list_request.format == ListResponseFormat.BASIC:
                    response = b"file1.txt\nfile2.txt\nsubdir"
                else:  # DETAIL
                    response = b"file1.txt|1024|2024-01-01\nfile2.txt|2048|2024-01-02\nsubdir|0|2024-01-03"

                # 应用过滤器
                if list_request.filter == ListFilter.FILES_ONLY:
                    response = b"\n".join(
                        [
                            line
                            for line in response.split(b"\n")
                            if b"|" in line and not line.endswith(b"|2024-01-03")
                        ]
                    )
                elif list_request.filter == ListFilter.DIRS_ONLY:
                    response = b"\n".join(
                        [
                            line
                            for line in response.split(b"\n")
                            if b"|" not in line or line.endswith(b"|2024-01-03")
                        ]
                    )

                self.responses[header.msg_type] = (MessageType.LIST_RESPONSE, response)
                return True

            except Exception as e:
                logger.error(f"Error handling LIST request: {e}")
                self.responses[header.msg_type] = (
                    MessageType.LIST_ERROR,
                    str(e).encode(),
                )
                self.handler.state = ProtocolState.ERROR
                return False

        def handle_nlst_request(header: ProtocolHeader, payload: bytes) -> bool:
            """处理NLST请求"""
            logger.info("Handling NLST request")
            if not self.handler.check_state(ProtocolState.CONNECTED):
                self.handler.state = ProtocolState.ERROR
                return False

            try:
                # 解析过滤器
                filter_type = (
                    ListFilter(int.from_bytes(payload[:4], "big"))
                    if payload
                    else ListFilter.ALL
                )

                # 生成简单文件名列表
                response = b"file1.txt\nfile2.txt\nsubdir"

                # 应用过滤器
                if filter_type == ListFilter.FILES_ONLY:
                    response = b"\n".join(
                        [
                            name
                            for name in response.split(b"\n")
                            if not name.endswith(b"dir")
                        ]
                    )
                elif filter_type == ListFilter.DIRS_ONLY:
                    response = b"\n".join(
                        [
                            name
                            for name in response.split(b"\n")
                            if name.endswith(b"dir")
                        ]
                    )

                self.responses[header.msg_type] = (MessageType.NLST_RESPONSE, response)
                return True

            except Exception as e:
                logger.error(f"Error handling NLST request: {e}")
                self.responses[header.msg_type] = (
                    MessageType.LIST_ERROR,
                    str(e).encode(),
                )
                self.handler.state = ProtocolState.ERROR
                return False

        # 注册所有处理器
        self.handler.register_handler(MessageType.HANDSHAKE, handle_handshake)
        self.handler.register_handler(MessageType.FILE_REQUEST, handle_file_request)
        self.handler.register_handler(MessageType.FILE_DATA, handle_file_data)
        self.handler.register_handler(MessageType.CLOSE, handle_close)
        self.handler.register_handler(MessageType.ERROR, handle_error)
        # 注册文件列表处理器
        self.handler.register_handler(MessageType.LIST_REQUEST, handle_list_request)
        self.handler.register_handler(MessageType.NLST_REQUEST, handle_nlst_request)

    def test_file_transfer_sequence(self):
        """测试完整的文件传输序列"""
        # 1. 握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        self.assertEqual(self.handler.state, ProtocolState.CONNECTED)

        # 2. 发送文件请求
        self.client.send_message(MessageType.FILE_REQUEST, b"test.txt")
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        self.assertEqual(self.handler.state, ProtocolState.TRANSFERRING)

        # 3. 发送文件数据
        file_data = b"Hello, World!"
        self.client.send_message(MessageType.FILE_DATA, file_data)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        response_type, response_payload = self.responses[msg_header.msg_type]
        self.test_socket.send_message(response_type, response_payload)
        resp_header, resp_payload = self.client.receive_message()
        self.assertEqual(resp_payload, b"DATA_RECEIVED")

    def test_invalid_message_sequence(self):
        """测试无效的消息顺序"""
        # 尝试在握手前发送文件请求
        self.client.send_message(MessageType.FILE_REQUEST, b"test.txt")
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        self.assertEqual(self.handler.state, ProtocolState.INIT)

    def test_multiple_handshake_attempts(self):
        """测试多次握手尝试"""
        # 第一次握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        self.assertEqual(self.handler.state, ProtocolState.CONNECTED)

        # 尝试第二次握手
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        # 状态应该保持在CONNECTED
        self.assertEqual(self.handler.state, ProtocolState.CONNECTED)

        # 发送关闭消息
        self.client.send_message(MessageType.CLOSE, b"")
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 状态应该变为COMPLETED
        self.assertEqual(self.handler.state, ProtocolState.COMPLETED)

    def test_error_handling(self):
        """测试错误处理"""
        # 先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 发送错误消息
        self.client.send_message(MessageType.ERROR, b"Test error")
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        self.assertEqual(self.handler.state, ProtocolState.ERROR)

    def test_immediate_close(self):
        """测试直接关闭连接"""
        # 不进行握手，直接发送关闭消息
        self.client.send_message(MessageType.CLOSE, b"")
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)
        # 状态应该保持在INIT，因为没有先进行握手
        self.assertEqual(self.handler.state, ProtocolState.INIT)

    def test_message_with_invalid_checksum(self):
        """测试带有无效校验和的消息"""
        # 创建一个带有错误校验和的消息
        header = ProtocolHeader(
            magic=PROTOCOL_MAGIC,
            version=ProtocolVersion.V1,
            msg_type=MessageType.HANDSHAKE,
            payload_length=4,
            sequence_number=1,
            checksum=12345,  # 错误的校验和
            chunk_number=0,
            session_id=0,
        )
        payload = ProtocolVersion.V1.to_bytes(4, "big")

        # 处理消息
        self.handler.handle_message(header, payload)
        # 校验和错误，状态应该保持不变
        self.assertEqual(self.handler.state, ProtocolState.INIT)

    def test_list_request(self):
        """测试详细文件列表请求"""
        # 先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 创建LIST请求负载
        list_request = ListRequest(
            format=ListResponseFormat.DETAIL, filter=ListFilter.ALL, path="/"
        )
        list_payload = list_request.to_bytes()

        # 发送LIST请求
        self.client.send_message(MessageType.LIST_REQUEST, list_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 检查响应
        response_type, response_payload = self.responses[msg_header.msg_type]
        self.test_socket.send_message(response_type, response_payload)
        resp_header, resp_payload = self.client.receive_message()

        # 验证响应类型和内容
        self.assertEqual(resp_header.msg_type, MessageType.LIST_RESPONSE)
        # 验证响应内容格式是否正确
        response_lines = resp_payload.split(b"\n")
        for line in response_lines:
            if b"|" in line:  # 详细格式应该包含分隔符
                parts = line.split(b"|")
                self.assertEqual(len(parts), 3)  # 文件名|大小|时间

    def test_nlst_request(self):
        """测试简单文件名列表请求"""
        # 先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 发送NLST请求
        filter_payload = ListFilter.ALL.to_bytes(4, "big")
        self.client.send_message(MessageType.NLST_REQUEST, filter_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 检查响应
        response_type, response_payload = self.responses[msg_header.msg_type]
        self.test_socket.send_message(response_type, response_payload)
        resp_header, resp_payload = self.client.receive_message()

        # 验证响应类型和内容
        self.assertEqual(resp_header.msg_type, MessageType.NLST_RESPONSE)
        # 解析并验证文件名列表

    def test_list_with_filter(self):
        """测试带过滤条件的文件列表请求"""
        # 先进行握手
        handshake_payload = ProtocolVersion.V1.to_bytes(4, "big")
        self.client.send_message(MessageType.HANDSHAKE, handshake_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 创建带过滤条件的LIST请求
        list_request = ListRequest(
            format=ListResponseFormat.DETAIL,  # 使用详细格式以便验证内容
            filter=ListFilter.FILES_ONLY,  # 只请求文件
            path="/",
        )
        filter_payload = list_request.to_bytes()

        # 发送LIST请求
        self.client.send_message(MessageType.LIST_REQUEST, filter_payload)
        msg_header, msg_payload = self.test_socket.receive_message()
        self.handler.handle_message(msg_header, msg_payload)

        # 检查响应
        response_type, response_payload = self.responses[msg_header.msg_type]
        self.test_socket.send_message(response_type, response_payload)
        resp_header, resp_payload = self.client.receive_message()

        # 验证响应类型
        self.assertEqual(resp_header.msg_type, MessageType.LIST_RESPONSE)

        # 验证响应内容只包含文件,不包含目录
        response_lines = resp_payload.split(b"\n")
        for line in response_lines:
            # 检查每一行是否都是文件(包含大小信息)且不是目录
            parts = line.split(b"|")
            self.assertEqual(len(parts), 3)  # 确保格式正确
            self.assertNotEqual(parts[1], b"0")  # 目录大小通常为0
            self.assertFalse(parts[0].endswith(b"dir"))  # 确保不是目录


if __name__ == "__main__":
    unittest.main()
