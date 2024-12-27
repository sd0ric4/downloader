import socket
import struct
import hashlib
import json
import logging
import os
from enum import IntEnum
from typing import Optional, Dict, Any, Tuple, Union, Callable
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProtocolVersion(IntEnum):
    V1 = 1


class MessageType(IntEnum):
    HANDSHAKE = 1
    FILE_REQUEST = 2
    FILE_METADATA = 3
    FILE_DATA = 4
    CHECKSUM_VERIFY = 5
    ERROR = 6
    ACK = 7
    RESUME_REQUEST = 8  # 新增: 断点续传请求类型


@dataclass
class ProtocolHeader:
    version: int
    msg_type: MessageType
    payload_length: int
    sequence_number: int
    checksum: str
    chunk_number: int = 0  # 新增: 用于断点续传的块编号

    @classmethod
    def from_bytes(cls, header_bytes: bytes) -> "ProtocolHeader":
        version, msg_type, payload_len, seq_num, chunk_num = struct.unpack(
            "!HHIII", header_bytes[:16]
        )
        checksum = header_bytes[16:].decode("utf-8")
        return cls(
            version, MessageType(msg_type), payload_len, seq_num, checksum, chunk_num
        )

    def to_bytes(self) -> bytes:
        header = struct.pack(
            "!HHIII",
            self.version,
            self.msg_type,
            self.payload_length,
            self.sequence_number,
            self.chunk_number,
        )
        return header + self.checksum.encode("utf-8")


class ProtocolError(Exception):
    pass


class SecurityError(ProtocolError):
    pass


class ChecksumError(SecurityError):
    pass


class EnhancedSocket(socket.socket):
    HEADER_SIZE = 48  # 增加了4字节用于chunk_number
    MAX_PAYLOAD_SIZE = 65536
    TIMEOUT = 30
    MAX_RETRIES = 3

    def __init__(self, sock: Optional[socket.socket] = None):
        if sock is None:
            super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        else:
            fd = sock.detach()
            super().__init__(fileno=fd)
            self.settimeout(sock.gettimeout())

        self.sequence_number = 0
        self.settimeout(self.TIMEOUT)

    def send_message(
        self, msg_type: MessageType, payload: bytes, chunk_number: int = 0
    ) -> None:
        if len(payload) > self.MAX_PAYLOAD_SIZE:
            raise ValueError(
                f"Payload size exceeds maximum ({self.MAX_PAYLOAD_SIZE} bytes)"
            )

        checksum = hashlib.md5(payload).hexdigest()

        header = ProtocolHeader(
            version=ProtocolVersion.V1,
            msg_type=msg_type,
            payload_length=len(payload),
            sequence_number=self.sequence_number,
            checksum=checksum,
            chunk_number=chunk_number,
        )

        for attempt in range(self.MAX_RETRIES):
            try:
                self._send_all(header.to_bytes())
                self._send_all(payload)
                # 等待ACK
                if msg_type == MessageType.FILE_DATA:
                    self._wait_for_ack()
                self.sequence_number += 1
                break
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.error(
                        f"Failed to send message after {self.MAX_RETRIES} attempts"
                    )
                    raise
                logger.warning(f"Retry attempt {attempt + 1} after error: {e}")
                continue

    def _wait_for_ack(self) -> None:
        """等待接收ACK消息"""
        msg_type, _ = self.receive_message()
        if msg_type != MessageType.ACK:
            raise ProtocolError(f"Expected ACK, got {msg_type}")

    def receive_message(self) -> Tuple[MessageType, bytes]:
        for attempt in range(self.MAX_RETRIES):
            try:
                header_bytes = self._recv_all(self.HEADER_SIZE)
                header = ProtocolHeader.from_bytes(header_bytes)
                payload = self._recv_all(header.payload_length)

                # 验证校验和
                received_checksum = hashlib.md5(payload).hexdigest()
                if received_checksum != header.checksum:
                    raise ChecksumError(
                        f"Checksum mismatch. Expected: {header.checksum}, "
                        f"Received: {received_checksum}"
                    )

                # 验证序列号
                if header.sequence_number != self.sequence_number:
                    raise ProtocolError(
                        f"Sequence number mismatch. Expected: {self.sequence_number}, "
                        f"Received: {header.sequence_number}"
                    )

                # 发送ACK
                if header.msg_type == MessageType.FILE_DATA:
                    self.send_message(MessageType.ACK, b"")

                self.sequence_number += 1
                return header.msg_type, payload

            except ChecksumError:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                logger.warning(f"Checksum error, retry attempt {attempt + 1}")
                continue
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                raise

    def _send_all(self, data: bytes) -> None:
        total_sent = 0
        while total_sent < len(data):
            sent = self.send(data[total_sent:])
            if sent == 0:
                raise ProtocolError("Socket connection broken")
            total_sent += sent

    def _recv_all(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            packet = self.recv(size - len(data))
            if not packet:
                raise ProtocolError(
                    f"Connection closed after receiving {len(data)} of {size} bytes"
                )
            data.extend(packet)
        return bytes(data)


@dataclass
class TransferProgress:
    total_chunks: int
    current_chunk: int
    file_size: int
    bytes_transferred: int

    @property
    def percentage(self) -> float:
        return (
            (self.current_chunk / self.total_chunks) * 100
            if self.total_chunks > 0
            else 0
        )


class FileTransferClient:
    def __init__(self, host: str, port: int):
        self.socket = EnhancedSocket()
        self.host = host
        self.port = port
        self.transfer_state = {}  # 保存传输状态用于断点续传

    def download_file(
        self,
        filename: str,
        save_path: str,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
        resume: bool = False,
    ) -> None:
        try:
            self.socket.connect((self.host, self.port))
            self._send_handshake()

            start_chunk = 0
            if resume and os.path.exists(save_path):
                # 获取已下载的块数
                start_chunk = self._get_downloaded_chunks(save_path)
                self._send_resume_request(filename, start_chunk)
            else:
                self._send_file_request(filename)

            metadata = self._receive_file_metadata()
            file_size = metadata["file_size"]
            total_chunks = metadata["total_chunks"]
            chunk_size = metadata["chunk_size"]

            # 保存传输状态
            self.transfer_state = {
                "filename": filename,
                "save_path": save_path,
                "total_chunks": total_chunks,
                "chunk_size": chunk_size,
                "file_size": file_size,
                "file_checksum": metadata["file_checksum"],
            }

            mode = "ab" if resume else "wb"
            with open(save_path, mode) as f:
                bytes_transferred = start_chunk * chunk_size
                for chunk_num in range(start_chunk, total_chunks):
                    chunk = self._receive_file_chunk(chunk_num)
                    f.write(chunk)
                    bytes_transferred += len(chunk)

                    if progress_callback:
                        progress = TransferProgress(
                            total_chunks=total_chunks,
                            current_chunk=chunk_num + 1,
                            file_size=file_size,
                            bytes_transferred=bytes_transferred,
                        )
                        progress_callback(progress)

            # 验证完整性
            self._verify_checksum(save_path, metadata["file_checksum"])

        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            raise
        finally:
            self.socket.close()

    def _get_downloaded_chunks(self, file_path: str) -> int:
        """获取已下载的块数"""
        if not os.path.exists(file_path):
            return 0

        state = self.transfer_state
        if not state:
            return 0

        file_size = os.path.getsize(file_path)
        return file_size // state["chunk_size"]

    def _send_resume_request(self, filename: str, start_chunk: int) -> None:
        """发送断点续传请求"""
        request_data = {"filename": filename, "start_chunk": start_chunk}
        self.socket.send_message(
            MessageType.RESUME_REQUEST, json.dumps(request_data).encode()
        )

    def _send_handshake(self) -> None:
        handshake_data = {
            "version": ProtocolVersion.V1,
            "client_id": hashlib.md5(str(id(self)).encode()).hexdigest(),
        }
        self.socket.send_message(
            MessageType.HANDSHAKE, json.dumps(handshake_data).encode()
        )

    def _send_file_request(self, filename: str) -> None:
        request_data = {"filename": filename}
        self.socket.send_message(
            MessageType.FILE_REQUEST, json.dumps(request_data).encode()
        )

    def _receive_file_metadata(self) -> Dict[str, Any]:
        msg_type, payload = self.socket.receive_message()
        if msg_type != MessageType.FILE_METADATA:
            raise ProtocolError(f"Expected FILE_METADATA, got {msg_type}")
        return json.loads(payload.decode())

    def _receive_file_chunk(self, expected_chunk_num: int) -> bytes:
        msg_type, payload = self.socket.receive_message()
        if msg_type != MessageType.FILE_DATA:
            raise ProtocolError(f"Expected FILE_DATA, got {msg_type}")
        return payload

    def _verify_checksum(self, file_path: str, expected_checksum: str) -> None:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

        if hasher.hexdigest() != expected_checksum:
            raise SecurityError("Final file checksum verification failed")


class FileTransferServer:
    def __init__(self, host: str, port: int):
        self.socket = EnhancedSocket()
        # Enable socket reuse
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((host, port))
        self.socket.listen(5)
        self.chunk_size = 8192
        self.running = False
        self.clients = set()  # Track active client connections

    def serve_forever(self) -> None:
        self.running = True
        logger.info(f"Server listening on {self.socket.getsockname()}")

        try:
            while self.running:
                try:
                    self.socket.settimeout(1.0)  # Add timeout to accept
                    client_sock, addr = self.socket.accept()
                    logger.info(f"Accepted connection from {addr}")
                    client_socket = EnhancedSocket(client_sock)
                    self.clients.add(client_socket)
                    self._handle_client(client_socket)
                except socket.timeout:
                    continue  # Allow checking self.running
                except Exception as e:
                    if self.running:  # Only log if not shutting down
                        logger.error(f"Error handling client: {e}")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Gracefully shutdown the server"""
        self.running = False
        logger.info("Shutting down server...")

        # Close all client connections
        for client in self.clients:
            try:
                client.close()
            except Exception:
                pass
        self.clients.clear()

        # Close server socket
        try:
            self.socket.close()
        except Exception as e:
            logger.error(f"Error closing server socket: {e}")

    def _handle_client(self, client_socket: EnhancedSocket) -> None:
        try:
            self._handle_handshake(client_socket)

            # 接收文件请求或断点续传请求
            msg_type, payload = client_socket.receive_message()
            if msg_type == MessageType.RESUME_REQUEST:
                request_data = json.loads(payload.decode())
                filename = request_data["filename"]
                start_chunk = request_data["start_chunk"]
                self._send_file(client_socket, filename, start_chunk)
            elif msg_type == MessageType.FILE_REQUEST:
                request_data = json.loads(payload.decode())
                filename = request_data["filename"]
                self._send_file(client_socket, filename)
            else:
                raise ProtocolError(f"Unexpected message type: {msg_type}")

        except Exception as e:
            if self.running:  # Only send error if not shutting down
                error_msg = str(e).encode()
                try:
                    client_socket.send_message(MessageType.ERROR, error_msg)
                except Exception:
                    pass
            logger.error(f"Error serving client: {e}")
        finally:
            self.clients.remove(client_socket)
            client_socket.close()

    def _handle_handshake(self, client_socket: EnhancedSocket) -> None:
        msg_type, payload = client_socket.receive_message()
        if msg_type != MessageType.HANDSHAKE:
            raise ProtocolError(f"Expected HANDSHAKE, got {msg_type}")

        handshake_data = json.loads(payload.decode())
        if handshake_data["version"] != ProtocolVersion.V1:
            raise ProtocolError("Unsupported protocol version")

    def _send_file(
        self, client_socket: EnhancedSocket, filename: str, start_chunk: int = 0
    ) -> None:
        file_size = os.path.getsize(filename)
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size

        file_checksum = self._calculate_file_checksum(filename)

        metadata = {
            "file_size": file_size,
            "total_chunks": total_chunks,
            "chunk_size": self.chunk_size,
            "file_checksum": file_checksum,
        }
        client_socket.send_message(
            MessageType.FILE_METADATA, json.dumps(metadata).encode()
        )

        with open(filename, "rb") as f:
            # 如果是断点续传，跳到指定位置
            if start_chunk > 0:
                f.seek(start_chunk * self.chunk_size)

            chunk_num = start_chunk
            while chunk := f.read(self.chunk_size):
                client_socket.send_message(
                    MessageType.FILE_DATA, chunk, chunk_number=chunk_num
                )
                chunk_num += 1

    def _calculate_file_checksum(self, filename: str) -> str:
        hasher = hashlib.md5()
        with open(filename, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()


# 使用示例
if __name__ == "__main__":
    import argparse
    import sys
    import time
    import signal

    def signal_handler(signum, frame):
        """Handle interrupt signal"""
        print("\nReceived interrupt signal. Shutting down...")
        if "server" in globals():
            server.running = False

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def progress_handler(progress: TransferProgress):
        """处理并显示下载进度"""
        sys.stdout.write(
            f"\rProgress: {progress.percentage:.1f}% "
            f"({progress.bytes_transferred}/{progress.file_size} bytes) "
            f"[Chunk {progress.current_chunk}/{progress.total_chunks}]"
        )
        sys.stdout.flush()
        if progress.current_chunk == progress.total_chunks:
            print("\nDownload completed!")

    parser = argparse.ArgumentParser(description="Enhanced File Transfer Program")
    parser.add_argument("--mode", choices=["server", "client"], required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=12345)
    parser.add_argument("--file", help="File to transfer (client mode)")
    parser.add_argument("--save-path", help="Where to save the file (client mode)")
    parser.add_argument(
        "--resume", action="store_true", help="Resume interrupted download"
    )

    args = parser.parse_args()

    try:
        if args.mode == "server":
            server = FileTransferServer(args.host, args.port)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                logger.info("Server shutting down")
        else:
            if not args.file or not args.save_path:
                parser.error("--file and --save-path are required in client mode")

            client = FileTransferClient(args.host, args.port)
            try:
                client.download_file(
                    args.file,
                    args.save_path,
                    progress_callback=progress_handler,
                    resume=args.resume,
                )
            except KeyboardInterrupt:
                print(
                    "\nDownload interrupted. You can resume later using --resume flag"
                )
            except Exception as e:
                print(f"\nError during download: {e}")
                if not args.resume:
                    print("You can try to resume the download using --resume flag")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
