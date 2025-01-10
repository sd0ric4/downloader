import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from filetransfer.server.client import ThreadedClient


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from filetransfer.server.client import ThreadedClient


def download_file(
    host: str, port: int, remote_file: str, local_path: Path, logger: logging.Logger
):
    # 为每个下载任务创建新的客户端实例
    client = ThreadedClient(host, port)
    try:
        if not client.connect():
            logger.error(f"连接失败，无法下载 {remote_file}")
            return False

        result = client.download_file(remote_file, str(local_path))
        if result:
            logger.info(f"文件 {remote_file} 已下载到 {local_path}")
        else:
            logger.error(f"下载失败 {remote_file}")
        return result
    except Exception as e:
        logger.exception(f"下载文件时发生错误 {remote_file}")
        return False
    finally:
        client.close()


def test_parallel_downloads():
    logger = logging.getLogger(__name__)
    root_dir = Path("./test_files/root")
    root_dir.mkdir(parents=True, exist_ok=True)

    files_to_download = [
        ("你好.txt", "下载了的你好1.txt"),
    ]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for remote_file, local_name in files_to_download:
            local_path = root_dir / local_name
            futures.append(
                executor.submit(
                    download_file, "localhost", 8002, remote_file, local_path, logger
                )
            )

        for future in futures:
            future.result()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    test_parallel_downloads()
