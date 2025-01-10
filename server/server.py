import argparse
import asyncio
import logging
import os
from filetransfer.server.transfer import (
    ThreadedServer,
    ProtocolServer,
    AsyncProtocolServer,
    SelectServer,
)
from filetransfer.network import IOMode


def setup_logging(log_file=None):
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def create_directories(root_dir, temp_dir):
    for directory in [root_dir, temp_dir]:
        os.makedirs(directory, exist_ok=True)


async def run_async_server(args):
    server = AsyncProtocolServer(
        host=args.host, port=args.port, root_dir=args.root_dir, temp_dir=args.temp_dir
    )
    await server.start()


def run_server(server_type, args):
    server_classes = {
        "protocol": ProtocolServer,
        "threaded": ThreadedServer,
        "select": SelectServer,
    }

    ServerClass = server_classes[server_type]
    server = ServerClass(
        host=args.host,
        port=args.port,
        root_dir=args.root_dir,
        temp_dir=args.temp_dir,
        io_mode=IOMode[args.io_mode.upper()],
    )
    server.start()


def main():
    parser = argparse.ArgumentParser(description="File Transfer Server")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8001, help="Server port")
    parser.add_argument(
        "--root-dir", default="./server_files/root", help="Root directory"
    )
    parser.add_argument(
        "--temp-dir", default="./server_files/temp", help="Temp directory"
    )
    parser.add_argument("--log-file", help="Log file path")
    parser.add_argument(
        "--server-type",
        choices=["protocol", "threaded", "select", "async"],
        default="protocol",
        help="Server implementation type",
    )
    parser.add_argument(
        "--io-mode",
        choices=["single", "threaded", "nonblocking"],
        default="single",
        help="IO mode for non-async servers",
    )

    args = parser.parse_args()

    setup_logging(args.log_file)
    create_directories(args.root_dir, args.temp_dir)

    try:
        if args.server_type == "async":
            asyncio.run(run_async_server(args))
        else:
            run_server(args.server_type, args)
    except KeyboardInterrupt:
        logging.info("Server shutting down...")


if __name__ == "__main__":
    main()
