import logging
from pathlib import Path
from filetransfer.server.transfer import ThreadedServer


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


if __name__ == "__main__":
    setup_logging()

    root_dir = Path("./server_files/root")
    temp_dir = Path("./server_files/temp")
    root_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadedServer(
        host="localhost",
        port=8001,
        root_dir=str(root_dir),
        temp_dir=str(temp_dir),
    )

    try:
        server.start()
    except KeyboardInterrupt:
        logging.info("正在关闭服务器...")
        server.stop()
