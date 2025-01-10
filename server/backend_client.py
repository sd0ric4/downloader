from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import logging
from filetransfer.server.client import SingleThreadClient

# 设置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="File Transfer Client API")

# 全局客户端连接 “localhost:8001”
client = SingleThreadClient("localhost", 8001)


class DownloadRequest(BaseModel):
    remote_filename: str
    local_filename: str


@app.get("/files")
async def list_files():
    try:
        if not client.connect():
            raise HTTPException(status_code=500, detail="Failed to connect to server")

        file_list = client.list_files()
        client.close()
        return {"files": file_list}
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        client.close()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download")
async def download_file(request: DownloadRequest):
    try:
        if not client.connect():
            raise HTTPException(status_code=500, detail="Failed to connect to server")

        # 确保本地目录存在
        local_path = Path(request.local_filename)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # 执行下载
        result = client.download_file(request.remote_filename, str(local_path))
        client.close()

        if result:
            logger.info(f"Successfully downloaded {request.remote_filename}")
            return {"message": "Download successful"}
        else:
            raise HTTPException(status_code=500, detail="Download failed")
    except Exception as e:
        logger.error(f"Download error: {e}")
        client.close()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/progress/{filename}")
async def get_progress(filename: str):
    try:
        progress = client.get_download_progress(f"./test_files/root/{filename}")
        if progress is not None:
            return {"progress": progress * 100}  # 转换为百分比
        return {"progress": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8013)


if __name__ == "__main__":
    main()
