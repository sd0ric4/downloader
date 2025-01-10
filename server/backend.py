import argparse
import asyncio
import logging
import os
import time
from datetime import datetime
from queue import Queue
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from filetransfer.server.transfer import (
    ThreadedServer,
    ProtocolServer,
    AsyncProtocolServer,
    SelectServer,
)
from filetransfer.network import IOMode

# Create FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
current_server = None
server_process = None
log_queue = Queue(maxsize=1000)  # Store last 1000 log messages


class LogRecord(BaseModel):
    timestamp: str
    level: str
    module: str
    message: str


class ServerConfig(BaseModel):
    host: str = "localhost"
    port: int = 8001
    rootDir: str = "./server_files/root"
    tempDir: str = "./server_files/temp"
    serverType: str = "protocol"
    ioMode: str = "single"


class ServerControl(BaseModel):
    action: str
    config: ServerConfig


class QueueHandler(logging.Handler):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        try:
            # Format the log message
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "level": record.levelname,
                "module": record.module,
                "message": record.getMessage(),
            }

            # Add to queue, removing oldest if full
            if self.queue.full():
                self.queue.get()
            self.queue.put(log_entry)
        except Exception:
            self.handleError(record)


def setup_logging(log_file=None):
    # Create queue handler
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    handlers = [queue_handler]

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        handlers.append(file_handler)

    # Configure logging
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def create_directories(root_dir, temp_dir):
    for directory in [root_dir, temp_dir]:
        os.makedirs(directory, exist_ok=True)
        logging.info(f"Created directory: {directory}")


async def run_async_server(config: ServerConfig):
    server = AsyncProtocolServer(
        host=config.host,
        port=config.port,
        root_dir=config.rootDir,
        temp_dir=config.tempDir,
    )
    await server.start()


def run_server(server_type: str, config: ServerConfig):
    server_classes = {
        "protocol": ProtocolServer,
        "threaded": ThreadedServer,
        "select": SelectServer,
    }

    ServerClass = server_classes[server_type]
    server = ServerClass(
        host=config.host,
        port=config.port,
        root_dir=config.rootDir,
        temp_dir=config.tempDir,
        io_mode=IOMode[config.ioMode.upper()],
    )
    return server


@app.get("/api/server/logs")
async def get_logs():
    # Convert queue to list without removing items
    logs = list(log_queue.queue)
    return {"logs": logs}


@app.post("/api/server/control")
async def control_server(control: ServerControl):
    global current_server, server_process

    if control.action not in ["start", "stop"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    if control.action == "start" and current_server:
        raise HTTPException(status_code=400, detail="Server is already running")

    if control.action == "stop" and not current_server:
        raise HTTPException(status_code=400, detail="Server is not running")

    try:
        if control.action == "start":
            logging.info(f"Starting server with configuration: {control.config}")
            create_directories(control.config.rootDir, control.config.tempDir)

            if control.config.serverType == "async":
                logging.info("Starting async server")
                server_process = asyncio.create_task(run_async_server(control.config))
            else:
                logging.info(f"Starting {control.config.serverType} server")
                current_server = run_server(control.config.serverType, control.config)
                current_server.start()

            return {"status": "Server started successfully"}
        else:  # stop
            logging.info("Stopping server")
            if server_process:
                server_process.cancel()
                server_process = None
            if current_server:
                current_server.stop()
                current_server = None
            return {"status": "Server stopped successfully"}

    except Exception as e:
        logging.error(f"Server operation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/server/status")
async def server_status():
    status = "running" if (current_server or server_process) else "stopped"
    logging.info(f"Current server status: {status}")
    return {"status": status}


# Create a custom logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logging.info(f"{request.method} {request.url.path} completed in {duration:.2f}s")
    return response


# Serve static files
app.mount("/", StaticFiles(directory="static", html=True), name="static")


def main():
    parser = argparse.ArgumentParser(description="File Transfer Server with Web UI")
    parser.add_argument("--host", default="localhost", help="API server host")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    parser.add_argument("--log-file", help="Log file path")

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_file)

    # Start the FastAPI server
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
