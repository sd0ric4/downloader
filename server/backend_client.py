from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import logging
import asyncio
from collections import deque
from typing import Dict, Optional
from filetransfer.server.client import SingleThreadClient

# 设置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="File Transfer Client API")


class DownloadRequest(BaseModel):
    remote_filename: str
    local_filename: str


class DownloadStatus(BaseModel):
    remote_filename: str
    local_filename: str
    status: str  # pending/downloading/completed/failed
    progress: Optional[float] = None
    error: Optional[str] = None


# 存储下载状态
download_status = {}
# 下载队列
download_queue = deque()
# 当前活跃的下载任务
active_downloads: Dict[str, asyncio.Task] = {}


class AsyncDownloadManager:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.clients: Dict[str, SingleThreadClient] = {}
        self.max_concurrent_downloads = 3

    async def get_client(self, remote_filename: str) -> SingleThreadClient:
        """获取或创建客户端实例"""
        if remote_filename not in self.clients:
            client = SingleThreadClient(self.host, self.port)
            if not client.connect():
                raise HTTPException(
                    status_code=500, detail="Failed to connect to server"
                )
            self.clients[remote_filename] = client
        return self.clients[remote_filename]

    def remove_client(self, remote_filename: str):
        """清理客户端实例"""
        if remote_filename in self.clients:
            self.clients[remote_filename].close()
            del self.clients[remote_filename]

    async def list_files(self):
        """获取文件列表"""
        client = SingleThreadClient(self.host, self.port)
        try:
            if not client.connect():
                raise HTTPException(
                    status_code=500, detail="Failed to connect to server"
                )

            loop = asyncio.get_event_loop()
            file_list = await loop.run_in_executor(None, client.list_files)
            return file_list
        finally:
            client.close()

    async def download_file(self, request: DownloadRequest):
        """处理下载请求"""
        client = await self.get_client(request.remote_filename)
        try:
            # 确保本地目录存在
            local_path = Path(request.local_filename)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 更新状态为downloading
            download_status[request.remote_filename] = DownloadStatus(
                remote_filename=request.remote_filename,
                local_filename=request.local_filename,
                status="downloading",
                progress=0,
            )

            # 在执行器中运行下载操作
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, client.download_file, request.remote_filename, str(local_path)
            )

            if result:
                logger.info(f"Successfully downloaded {request.remote_filename}")
                download_status[request.remote_filename].status = "completed"
                download_status[request.remote_filename].progress = 1.0
            else:
                download_status[request.remote_filename].status = "failed"
                download_status[request.remote_filename].error = "Download failed"
                raise HTTPException(status_code=500, detail="Download failed")

        except Exception as e:
            logger.error(f"Download error: {e}")
            download_status[request.remote_filename].status = "failed"
            download_status[request.remote_filename].error = str(e)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            self.remove_client(request.remote_filename)


download_manager = AsyncDownloadManager("localhost", 8001)


async def process_download_queue():
    """处理下载队列的后台任务"""
    while True:
        # 检查是否可以启动新的下载
        while (
            len(active_downloads) < download_manager.max_concurrent_downloads
            and download_queue
        ):
            request = download_queue.popleft()
            # 创建新的下载任务
            task = asyncio.create_task(download_manager.download_file(request))
            active_downloads[request.remote_filename] = task

        # 清理已完成的下载任务
        for remote_filename in list(active_downloads.keys()):
            if active_downloads[remote_filename].done():
                del active_downloads[remote_filename]

        await asyncio.sleep(0.1)


@app.get("/files")
async def list_files():
    """获取可用文件列表"""
    try:
        file_list = await download_manager.list_files()
        return {"files": file_list}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download")
async def download_file(request: DownloadRequest):
    """添加下载请求到队列"""
    # 添加到下载队列
    download_queue.append(request)

    # 添加初始状态
    download_status[request.remote_filename] = DownloadStatus(
        remote_filename=request.remote_filename,
        local_filename=request.local_filename,
        status="pending",
    )

    return {"message": "Download request added to queue"}


@app.get("/download/progress/{remote_filename}")
async def get_download_status(remote_filename: str):
    """获取下载进度"""
    if remote_filename not in download_status:
        raise HTTPException(status_code=404, detail="Download not found")

    status = download_status[remote_filename]
    if status.status == "downloading":
        # 如果任务正在下载中，获取实时进度
        client = await download_manager.get_client(remote_filename)
        progress = client.get_download_progress(status.local_filename)
        if progress is not None:
            status.progress = progress

    return status


@app.on_event("startup")
async def startup_event():
    """启动时创建下载队列处理任务"""
    asyncio.create_task(process_download_queue())


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8013)


if __name__ == "__main__":
    main()
