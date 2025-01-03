from __future__ import annotations

import asyncio
import contextlib
import json
from http.client import responses
from typing import TYPE_CHECKING, Any

from jupyter_server.services.kernels.websocket import KernelWebsocketHandler as WSHandler
from pydantic import ValidationError
from tornado import web
from tornado.log import app_log as logger

from mkm.handlers.auth import authenticated
from mkm.handlers.mixins import CORSMixin, JSONErrorsMixin
from mkm.handlers.schema import AliasKernelPayload, CreateKernelPayload, KernelResponse
from mkm.jupyter_kernel_client.excs import (
    KernelCreationError,
    KernelExistsError,
    KernelNotFoundError,
    KernelRetrieveError,
    KernelWaitReadyTimeoutError,
    KernelResourceQuotaExceededError
)

if TYPE_CHECKING:
    from collections.abc import Awaitable


class MainKernelHandler(CORSMixin, JSONErrorsMixin, web.RequestHandler):
    @authenticated
    async def post(self):
        """Creates a new kernel instance.

        Returns:
            dict: JSON response containing the created kernel's information, excluding connection details.

        Raises:
            tornado.web.HTTPError: 400 Bad Request if request body is invalid or not JSON.
                500 Internal Server Error if kernel creation, retrieval or startup fails.

        Accepts a JSON request body containing kernel configuration parameters as defined in KernelPayload.
        Validates and processes the request to start a new kernel with the specified configuration.
        """

        try:
            req_body = CreateKernelPayload.model_validate_json(self.request.body)

            filtered_values = {k: v for k, v in req_body.env.items() if k.startswith("KERNEL_")}
            filtered_values.update({"KERNEL_SPEC_NAME": req_body.name})

            payload = AliasKernelPayload.model_validate(filtered_values)

        except ValidationError as e:
            raise web.HTTPError(422, f"Invalid request json body: {e}")  # noqa: B904

        kernel_manager = self.settings["kernel_manager"]
        try:
            kernel = await kernel_manager.astart_kernel(payload)
        except KernelExistsError as e:
            raise web.HTTPError(409, f"Kernel already exists: {e}")  # noqa: B904
        except KernelResourceQuotaExceededError as e:
            raise web.HTTPError(403, str(e))  # noqa: B904
        except KernelCreationError as e:
            raise web.HTTPError(500, f"Kernel creation error: {e}")  # noqa: B904
        except KernelRetrieveError as e:
            raise web.HTTPError(500, f"Kernel retrieve error then create success: {e}")  # noqa: B904
        except KernelWaitReadyTimeoutError as e:
            raise web.HTTPError(  # noqa: B904
                500, f"Kernel wait ready timeout error, please list the kernel a few seconds later: {e}"
            )

        self.finish(KernelResponse.model_validate(kernel).model_dump_json())

    @authenticated
    async def get(self):
        """Get the list of running kernels."""
        km = self.settings["kernel_manager"]
        try:
            kernels = await km.alist_kernels()
        except KernelRetrieveError as e:
            raise web.HTTPError(500, f"Kernel list error: {e}")  # noqa: B904

        self.finish(json.dumps([KernelResponse.model_validate(kernel).model_dump() for kernel in kernels]))

    @authenticated
    async def delete(self):
        """Delete kernel by kernel ids."""
        # now only support the kernel_spec_name in the request body env
        try:
            body = json.loads(self.request.body)
            kids = body["kernel_ids"]
        except (json.JSONDecodeError, KeyError) as e:
            raise web.HTTPError(400, f"Invalid request json body: {e}")  # noqa: B904

        km = self.settings["kernel_manager"]

        await asyncio.gather(*[km.aremove_kernel(kid) for kid in kids])

        self.finish()


class KernelHandler(CORSMixin, JSONErrorsMixin, web.RequestHandler):
    """Extends the jupyter_server kernel handler with token auth, CORS, and
    JSON errors.
    """

    @authenticated
    async def get(self, kernel_id: str):
        """Get the model for a kernel."""
        km = self.settings["kernel_manager"]
        try:
            kernel = await km.aget_kernel(kernel_id=kernel_id, serialize=True)
        except KernelNotFoundError as e:
            raise web.HTTPError(404, f"Kernel not found: {e}")  # noqa: B904
        except KernelRetrieveError as e:
            raise web.HTTPError(500, f"Kernel retrieve error: {e}")  # noqa: B904

        if kernel is None:
            raise web.HTTPError(404, f"Kernel not found: {kernel_id}")

        self.finish(KernelResponse.model_validate(kernel).model_dump_json())

    # delete kernel by id
    @authenticated
    async def delete(self, kernel_id: str):
        """Delete a kernel by id."""
        km = self.settings["kernel_manager"]
        await km.aremove_kernel(kernel_id)
        self.finish()


class KernelWebsocketHandler(WSHandler):  # type:ignore[misc]
    @property
    def kernel_manager(self):
        return self.settings["kernel_manager"]

    async def prepare(self, *, _redirect_to_login=True) -> Awaitable[None] | None:  # type:ignore[override]
        # noting to do ..
        ...

    async def pre_get(self):
        """Handle a pre_get."""
        try:
            kernel = self.kernel_manager.get_kernel(self.kernel_id)
        except KernelNotFoundError:
            raise web.HTTPError(404, f"Kernel not found: {self.kernel_id}")  # noqa: B904
        except KernelRetrieveError as e:
            logger.exception(f"get kernel error: {self.kernel_id}, error: {e}")

            raise web.HTTPError(500, f"Get kernel error: {self.kernel_id}")  # noqa: B904

        if kernel is None:
            raise web.HTTPError(500, f"Kernel not ready: {self.kernel_id}")

        self.connection = self.kernel_websocket_connection_class(parent=kernel, websocket_handler=self, log=logger)

        if self.get_argument("session_id", None):
            self.connection.session.session = self.get_argument("session_id")
        else:
            logger.warning("No session ID specified")
        if hasattr(self.connection, "prepare"):
            await self.connection.prepare()

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        """render custom error pages"""
        exc_info = kwargs.get("exc_info")
        message = ""
        status_message = responses.get(status_code, "Unknown HTTP Error")

        if exc_info:
            exception = exc_info[1]
            # get the custom message, if defined
            with contextlib.suppress(Exception):
                message = exception.log_message % exception.args

            # construct the custom reason, if defined
            reason = getattr(exception, "reason", "")
            if reason:
                status_message = reason
        else:
            exception = "(unknown)"

        # build template namespace
        ns = {
            "status_code": status_code,
            "status_message": status_message,
            "message": message,
            "exception": exception,
        }

        logger.error("WS error: %s", ns)

        self.set_status(status_code)
        self.finish(status_message)

    @authenticated
    async def get(self, kernel_id):
        """Handle a get request for a kernel."""
        self.kernel_id = kernel_id
        await self.pre_get()
        await super(WSHandler, self).get(kernel_id=kernel_id)


# -----------------------------------------------------------------------------
_kernel_id_regex = r"(?P<kernel_id>\w+-\w+-\w+-\w+-\w+)"

_kernel_handlers = [
    (r"/api/kernels", MainKernelHandler),
    (rf"/api/kernels/{_kernel_id_regex}", KernelHandler),
    (rf"/api/kernels/{_kernel_id_regex}/channels", KernelWebsocketHandler),
]
