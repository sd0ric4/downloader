from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import logging
from typing import Optional, Dict, List
from enum import Enum
import threading
import asyncio
from collections import deque
import time
import os
from filetransfer.server.transfer import (
    ThreadedServer,
    AsyncProtocolServer,
    SelectServer,
    ProtocolServer,
)
from filetransfer.network import IOMode

# 设置日志格式
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LogEntry(BaseModel):
    timestamp: str
    level: str
    module: str
    message: str


class LogStore:
    def __init__(self, maxlen=1000):
        self.logs = deque(maxlen=maxlen)

    def add_log(self, record):
        self.logs.append(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "module": record.name,
                "message": record.getMessage(),
            }
        )

    def get_logs(self):
        return list(self.logs)


class LogHandler(logging.Handler):
    def __init__(self, log_store):
        super().__init__()
        self.log_store = log_store

    def emit(self, record):
        self.log_store.add_log(record)


class ServerType(str, Enum):
    PROTOCOL = "protocol"
    THREADED = "threaded"
    SELECT = "select"
    ASYNC = "async"


class ServerIOMode(str, Enum):
    SINGLE = "single"
    THREADED = "threaded"
    NONBLOCKING = "nonblocking"
    ASYNC = "async"


class ServerConfig(BaseModel):
    host: str = "localhost"
    port: int = 8001
    root_dir: str = "./server_files/root"
    temp_dir: str = "./server_files/temp"
    server_type: ServerType = ServerType.PROTOCOL
    io_mode: ServerIOMode = ServerIOMode.SINGLE


class ServerStatus(BaseModel):
    running: bool
    server_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    active_connections: Optional[int] = None


class ServerState:
    def __init__(self):
        self.instance = None
        self.config = None
        self.server_thread = None
        self.event_loop = None
        self.async_task = None


app = FastAPI(title="File Transfer Server Control")

# 全局状态
server_state = ServerState()
log_store = LogStore()

# 添加日志处理器
logger.addHandler(LogHandler(log_store))


def create_directories(root_dir: str, temp_dir: str):
    """创建必要的目录"""
    for directory in [root_dir, temp_dir]:
        os.makedirs(directory, exist_ok=True)


def run_sync_server(server):
    """运行同步服务器"""
    try:
        server.start()
    except Exception as e:
        logger.error(f"Server error: {e}")


async def run_async_server(server):
    """运行异步服务器"""
    try:
        await server.start()
    except Exception as e:
        logger.error(f"Async server error: {e}")


@app.post("/server/start")
async def start_server(config: ServerConfig):
    global server_state

    if server_state.instance:
        raise HTTPException(status_code=400, detail="Server is already running")

    try:
        create_directories(config.root_dir, config.temp_dir)
        logger.info(f"Starting server with config: {config.dict()}")

        if config.server_type == ServerType.ASYNC:
            # 处理异步服务器
            server_state.instance = AsyncProtocolServer(
                host=config.host,
                port=config.port,
                root_dir=config.root_dir,
                temp_dir=config.temp_dir,
            )
            server_state.event_loop = asyncio.new_event_loop()
            server_state.async_task = server_state.event_loop.create_task(
                run_async_server(server_state.instance)
            )
            server_state.server_thread = threading.Thread(
                target=lambda: server_state.event_loop.run_forever(), daemon=True
            )
            server_state.server_thread.start()
        else:
            # 处理同步服务器
            server_classes = {
                ServerType.PROTOCOL: ProtocolServer,
                ServerType.THREADED: ThreadedServer,
                ServerType.SELECT: SelectServer,
            }

            ServerClass = server_classes[config.server_type]
            server_state.instance = ServerClass(
                host=config.host,
                port=config.port,
                root_dir=config.root_dir,
                temp_dir=config.temp_dir,
                io_mode=IOMode[config.io_mode.upper()],
            )

            server_state.server_thread = threading.Thread(
                target=run_sync_server, args=(server_state.instance,), daemon=True
            )
            server_state.server_thread.start()

        server_state.config = config
        logger.info("Server started successfully")
        return {"message": "Server started successfully"}

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        server_state = ServerState()  # 失败时重置状态
        raise HTTPException(status_code=500, detail=f"Failed to start server: {str(e)}")


@app.post("/server/stop")
async def stop_server():
    global server_state

    if not server_state.instance:
        raise HTTPException(status_code=400, detail="Server is not running")

    try:
        logger.info("Stopping server...")
        if isinstance(server_state.instance, AsyncProtocolServer):
            # 停止异步服务器
            if server_state.event_loop:
                await server_state.instance.stop()
                server_state.event_loop.call_soon_threadsafe(
                    server_state.event_loop.stop
                )
                server_state.server_thread.join(timeout=5)
        else:
            # 停止同步服务器
            server_state.instance.stop()
            if server_state.server_thread:
                server_state.server_thread.join(timeout=5)

        logger.info("Server stopped successfully")
        server_state = ServerState()  # 重置状态
        return {"message": "Server stopped successfully"}

    except Exception as e:
        logger.error(f"Failed to stop server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop server: {str(e)}")


@app.get("/server/status")
async def get_server_status():
    if not server_state.instance:
        return ServerStatus(running=False)

    try:
        active_connections = 0
        if hasattr(server_state.instance, "session_manager"):
            active_connections = (
                server_state.instance.session_manager.get_active_sessions_count()
            )

        status = ServerStatus(
            running=True,
            server_type=(
                server_state.config.server_type if server_state.config else None
            ),
            host=server_state.config.host if server_state.config else None,
            port=server_state.config.port if server_state.config else None,
            active_connections=active_connections,
        )
        return status

    except Exception as e:
        logger.error(f"Error getting server status: {e}")
        return ServerStatus(running=True)


@app.get("/server/logs")
async def get_logs():
    """获取服务器日志"""
    return {"logs": log_store.get_logs()}


def main():
    """主函数"""
    logger.info("Starting File Transfer Server Control...")
    uvicorn.run(app, host="0.0.0.0", port=8012)


if __name__ == "__main__":
    main()
