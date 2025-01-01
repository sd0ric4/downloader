import queue
import threading
from .base import BaseProtocolHandler
from filetransfer.protocol import ProtocolHeader


class ThreadedProtocolHandler(BaseProtocolHandler):
    """多线程模式处理器"""

    def __init__(self, max_workers: int = 4):
        super().__init__()
        self.max_workers = max_workers
        self.task_queue = queue.Queue()
        self.workers = []
        self._start_workers()

    def _start_workers(self):
        """启动工作线程"""
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop)
            worker.daemon = True
            worker.start()
            self.workers.append(worker)

    def _worker_loop(self):
        """工作线程主循环"""
        while True:
            try:
                task = self.task_queue.get()
                if task is None:
                    break
                header, payload = task
                self._process_message(header, payload)
                self.task_queue.task_done()
            except Exception as e:
                self.logger.error(f"Worker error: {e}")

    def _dispatch_message(self, header: ProtocolHeader, payload: bytes):
        """将消息放入队列进行处理"""
        self.task_queue.put((header, payload))

    def _process_message(self, header: ProtocolHeader, payload: bytes):
        """具体的消息处理逻辑"""
        if not self.verify_checksum(header, payload):
            self.logger.error("Checksum verification failed")
            return

        handler = self.handlers.get(header.msg_type)
        if handler:
            try:
                handler(header, payload)
            except Exception as e:
                self.logger.error(f"Message handler error: {e}")
        else:
            self.logger.warning(f"No handler for message type: {header.msg_type}")

    def shutdown(self):
        """关闭处理器"""
        for _ in self.workers:
            self.task_queue.put(None)
        for worker in self.workers:
            worker.join()
