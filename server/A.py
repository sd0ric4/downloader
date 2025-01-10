import logging
from pathlib import Path
from filetransfer.server.client import SingleThreadClient


def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def test_download():
    logger = logging.getLogger(__name__)

    # 创建本地目录
    root_dir = Path("./test_files/root")
    root_dir.mkdir(parents=True, exist_ok=True)

    # 创建客户端并连接
    client = SingleThreadClient("localhost", 8002)
    if not client.connect():
        logger.error("连接服务器失败")
        return

    try:
        file_list = client.list_files()
        logger.info(f"服务器上的文件列表: {file_list}")
        # 下载文件名（假设服务器上已经有这个文件）
        remote_filename = "测试.txt"
        local_download_path = root_dir / "测试.txt"

        # 执行下载
        result = client.download_file(remote_filename, str(local_download_path))

        if result:
            logger.info(f"文件 {remote_filename} 下载成功到 {local_download_path}")
            # 可以添加检查文件大小等额外逻辑
        else:
            logger.error(f"文件 {remote_filename} 下载失败")

    except Exception as e:
        logger.exception("下载过程中发生错误")
    finally:
        client.close()


if __name__ == "__main__":
    setup_logging()
    test_download()
