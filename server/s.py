from filetransfer.server.transfer import ThreadedServer, ProtocolServer
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,  # 可以改为 DEBUG 查看更详细的日志
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        # 如果需要，可以同时添加文件日志处理器
        # logging.FileHandler('server.log')
    ],
)


# 之后再创建和启动服务器
from filetransfer.server.transfer import ProtocolServer

server = ProtocolServer(
    host="localhost",
    port=8001,
    root_dir="./server_files/root",
    temp_dir="./server_files/temp",
)
server.start()
