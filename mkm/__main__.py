import asyncio
import os

from jupyter_server.services.kernels.connection.channels import ZMQChannelsWebsocketConnection
from tornado import web
from tornado.log import app_log

from mkm.handlers import default_handlers
from mkm.kernel_manager import KubeMultiKernelManager
from mkm.log import setup_logging


async def main(port: int):
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    allow_unauthenticated_access = os.getenv("ALLOW_UNAUTHENTICATED_ACCESS", "false").lower() in [
        "true",
        "1",
        "yes",
        "y",
        "t",
        "1",
    ]

    if allow_unauthenticated_access:
        app_log.warning("allow_unauthenticated_access is set to True, current user setting to anonymous")

    user_in_header = os.getenv("USER_IN_HEADER", "X-Forwarded-User")

    app = web.Application(
        handlers=default_handlers,
        kernel_manager=KubeMultiKernelManager(),
        user_in_header=user_in_header,
        allow_unauthenticated_access=allow_unauthenticated_access,
        kernel_websocket_connection_class=ZMQChannelsWebsocketConnection,
    )

    app_log.info("Starting server on port %d", port)

    app.listen(port)
    shutdown_event = asyncio.Event()
    await shutdown_event.wait()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("--port", type=int, default=8888)
    args = parser.parse_args()

    asyncio.run(main(args.port))
