from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http import HTTPStatus
from typing import ClassVar

import kubernetes.client.models
import six
from dateutil.parser import parse
from kubernetes import client, config
from kubernetes.client import ApiException

from mkm.jupyter_kernel_client import models as jkmodels
from mkm.jupyter_kernel_client.constants import (
    KERNEL_GROUP,
    KERNEL_ID,
    KERNEL_KIND,
    KERNEL_MANAGER_NAME,
    KERNEL_PLURAL,
    KERNEL_SPEC_NAME,
    KERNEL_VERSION,
)
from mkm.jupyter_kernel_client.excs import (
    KernelCreationError,
    KernelDeleteError,
    KernelExistsError,
    KernelNotFoundError,
    KernelRetrieveError,
    KernelWaitReadyTimeoutError,
)
from mkm.jupyter_kernel_client.models import V1Kernel
from mkm.jupyter_kernel_client.schema import KernelModel, KernelPayload

client_logger = logging.getLogger("jupyter_kernel_client.client")
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)
client_logger.addHandler(handler)


class JupyterKernelClient:
    """Client for managing Jupyter kernels in Kubernetes.

    This class provides methods to create, list, get and delete Jupyter kernels running as Kubernetes custom resources.
    It handles serialization/deserialization of kernel specifications and manages communication with the Kubernetes API.

    Attributes:
        PRIMITIVE_TYPES: Tuple of primitive Python types used for serialization
        NATIVE_TYPES_MAPPING: Dict mapping type strings to Python types
    """

    PRIMITIVE_TYPES = (*[float, bool, bytes, six.text_type], *six.integer_types)
    NATIVE_TYPES_MAPPING: ClassVar[dict] = {
        "int": int,
        "long": int if not six.PY2 else long,  # noqa: F821
        "float": float,
        "str": str,
        "bool": bool,
        "date": datetime.date,
        "datetime": datetime.datetime,
        "object": object,
    }

    def __init__(
        self,
        group: str = KERNEL_GROUP,
        version: str = KERNEL_VERSION,
        kind: str = KERNEL_KIND,
        plural: str = KERNEL_PLURAL,
        timeout: int = 60,
        logger: logging.Logger | None = None,
        **kwargs,
    ) -> None:
        """Initialize the Kernel client.

        Args:
            group (str, optional): kubernetes kernel cr group. Defaults to "jupyter.org".
            version (str, optional): kubernetes kernel cr version. Defaults to "v1".
            kind (str, optional): kubernetes kernel cr kind. Defaults to "Kernel".
            plural (str, optional): kubernetes kernel cr plural. Defaults to "kernels".
            timeout (int, optional): default timeout for kubernetes api calls. Defaults to 60.
        """

        self.logger = logger or client_logger

        if kwargs.pop("incluster", None):
            self.logger.warning("`incluster` is deprecated, will be removed in a future version")

        try:
            config.load_incluster_config()
        except config.ConfigException:
            self.logger.warning("Failed to load incluster config, trying to load kube config")
            config.load_kube_config()

        self.kind = kind
        self.plural = plural
        self.group = group
        self.version = version
        self.timeout = timeout

        self.api_version = f"{group}/{version}"
        self.api_instance = client.CustomObjectsApi()
        self.executor = ThreadPoolExecutor()

    @property
    def loop(self):
        """Get or create an asyncio event loop.

        Returns:
            asyncio.AbstractEventLoop: The current or new event loop
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.logger.warning("Failed to get running loop, creating a new one")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop

    async def acreate(
        self, payload: KernelPayload, timeout: int | None = None, *, wait_for_ready: bool = True, **kwargs
    ) -> KernelModel:
        """Asynchronously create a kernel resource in Kubernetes.

        Creates a new Jupyter kernel as a Kubernetes custom resource. Can optionally wait for the kernel
        to be ready before returning.

        Args:
            payload (KernelPayload): The kernel specification and configuration
            timeout (int | None, optional): Timeout in seconds for kernel creation. Defaults to None.
            wait_for_ready (bool, optional): Whether to wait for kernel to be ready. Defaults to True.
            **kwargs: Additional arguments passed to Kubernetes API

        Returns:
            KernelModel: The created kernel's specification and status

        Raises:
            KernelCreationError: If kernel creation fails
            KernelWaitReadyTimeoutError: If kernel does not become ready within timeout
        """
        timeout = timeout or self.timeout
        kernel_spec_name = payload.kernel_spec_name.value
        kernel_dict = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {
                "labels": {
                    KERNEL_ID: payload.kernel_id,
                    KERNEL_MANAGER_NAME: f"{kernel_spec_name}-{payload.kernel_id}",
                    KERNEL_SPEC_NAME: kernel_spec_name,
                },
                "name": f"{kernel_spec_name}-{payload.kernel_id}",
                "namespace": payload.kernel_namespace,
            },
            "spec": {
                "idleTimeoutSeconds": payload.kernel_idle_timeout,
                "cullingIntervalSeconds": 60,
                "kernelConnectionConfig": payload.kernel_connection_info.model_dump(by_alias=True),
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "env": [
                                    {"name": k, "value": v}
                                    for k, v in payload.model_dump(by_alias=True).items()
                                    if k.startswith("KERNEL_")
                                ],
                                "image": payload.kernel_image,
                                "name": "ipykernel",
                                "volumeMounts": payload.kernel_volume_mounts,
                                "workingDir": payload.kernel_working_dir,
                                "command": ["python", "-m", "ipykernel", "-f", "$(KERNEL_CONNECTION_FILE_PATH)"],
                            }
                        ],
                        "restartPolicy": "Never",
                        "volumes": payload.kernel_volumes,
                    }
                },
            },
        }

        kernel = self._deserialize(kernel_dict, V1Kernel)

        try:
            partial_func = partial(
                self.api_instance.create_namespaced_custom_object, _request_timeout=timeout, **kwargs
            )
            await self.loop.run_in_executor(
                self.executor, partial_func, self.group, self.version, payload.kernel_namespace, self.plural, kernel
            )

        except ApiException as e:
            traceback_str = traceback.format_exc()
            if e.status == HTTPStatus.CONFLICT.value:
                self.logger.debug("Kernel %s already exists", payload.kernel_id)
                error_msg = (
                    f"Kernel already exists: kernel-id: {payload.kernel_id}, namespace: {payload.kernel_namespace}"
                )
                raise KernelExistsError(error_msg) from e
            if e.status == HTTPStatus.FORBIDDEN.value:
                self.logger.exception(traceback_str)
                error_msg = "Kernel creation is forbidden (403). Check permissions or resource quota limits."
                raise KernelCreationError(error_msg) from e

            error_msg = f"Error creating kernel: {e.status}\n{e.reason}"
            self.logger.exception(traceback_str)
            raise KernelCreationError(error_msg) from e

        if wait_for_ready:
            _is_ready = await self._wait_for_kernel_ready(
                kernel_id=payload.kernel_id, namespace=payload.kernel_namespace, timeout=timeout
            )
            if not _is_ready:
                error_msg = f"Kernel {payload.kernel_id} in namespace {payload.kernel_namespace} is not ready"
                self.logger.error(error_msg)
                raise KernelWaitReadyTimeoutError(error_msg)

        return await self.aget_kernel_by_id(
            kernel_id=payload.kernel_id, namespace=payload.kernel_namespace, timeout=timeout
        )

    async def alist(self, namespace: str | None = None, timeout=None, **kwargs) -> list[KernelModel]:
        """Asynchronously list all kernel resources in a namespace or across all namespaces.

        Args:
            namespace (str | None, optional): The namespace to list kernels from. If None, lists kernels across all namespaces.
                Defaults to None.
            timeout (int | None, optional): Timeout in seconds for listing kernels. If None, uses the client's default timeout.
                Defaults to None.
            **kwargs: Additional keyword arguments to pass to the Kubernetes API.

        Returns:
            list[KernelModel]: List of kernel models representing the kernel resources.

        Raises:
            KernelRetrieveError: If there is an error retrieving the kernel list from the API.
        """
        timeout = timeout or self.timeout

        if namespace is None:
            partial_func = partial(
                self.api_instance.list_cluster_custom_object,
                group=self.group,
                version=self.version,
                plural=self.plural,
                _request_timeout=timeout,
                **kwargs,
            )
        else:
            partial_func = partial(
                self.api_instance.list_namespaced_custom_object,
                group=self.group,
                version=self.version,
                plural=self.plural,
                namespace=namespace,
                _request_timeout=timeout,
                **kwargs,
            )

        try:
            kernels = await self.loop.run_in_executor(self.executor, partial_func)
        except ApiException as e:
            self.logger.exception(traceback.format_exc())
            error_msg = f"Error getting kernel: {e.status}\n{e.reason}"
            raise KernelRetrieveError(error_msg) from e

        return [KernelModel.model_validate(kernel) for kernel in kernels["items"]]

    async def aget_kernel_by_id(
        self, kernel_id: str, namespace: str | None = None, timeout: int = 60, **kwargs
    ) -> KernelModel | None:
        """Asynchronously get a kernel resource by its ID.

        Args:
            kernel_id (str): The ID of the kernel to retrieve.
            namespace (str | None, optional): The namespace to search in. If None, searches across all namespaces.
                Defaults to None.
            timeout (int | None, optional): Timeout in seconds for retrieving the kernel. If None, uses the client's default timeout.
                Defaults to None.
            **kwargs: Additional keyword arguments to pass to the Kubernetes API.

        Returns:
            KernelModel: The kernel model representing the found kernel resource.

        Raises:
            KernelRetrieveError: If there is an error retrieving the kernel from the API.
            KernelNotFoundError: If no kernel with the given ID is found.
        """
        if namespace is None:
            partial_func = partial(
                self.api_instance.list_cluster_custom_object,
                group=self.group,
                version=self.version,
                plural=self.plural,
                _request_timeout=timeout,
                label_selector=f"{KERNEL_ID}={kernel_id}",
                limit=1,
                **kwargs,
            )
        else:
            partial_func = partial(
                self.api_instance.list_namespaced_custom_object,
                group=self.group,
                version=self.version,
                plural=self.plural,
                namespace=namespace,
                _request_timeout=timeout,
                label_selector=f"{KERNEL_ID}={kernel_id}",
                limit=1,
                **kwargs,
            )

        try:
            kernels = await self.loop.run_in_executor(self.executor, partial_func)
        except ApiException as e:
            self.logger.exception(traceback.format_exc())
            error_msg = f"Error getting kernel: {e.status}\n{e.reason}"
            raise KernelRetrieveError(error_msg) from e

        if len(kernels["items"]) == 0:
            error_msg: str = f"Could not find kernel with id {kernel_id}"
            raise KernelNotFoundError(error_msg)

        return KernelModel.model_validate(kernels["items"][0])

    async def adelete_by_kernel_id(
        self, kernel_id: str, namespace: str | None = None, timeout: int = 60, **kwargs
    ) -> None:
        """Asynchronously delete a kernel resource by kernel ID.

        This method attempts to delete a Jupyter kernel resource from Kubernetes using its kernel ID.
        It first retrieves the kernel details using the ID, then deletes the corresponding resource.
        If the kernel is not found or already deleted, the method returns silently.

        Args:
            kernel_id (str): The ID of the kernel to delete.
            namespace (str | None, optional): The namespace to search for the kernel. If None, searches across all namespaces.
                Defaults to None.
            timeout (int | None, optional): Timeout in seconds for the deletion operation. If None, uses the client's default timeout.
                Defaults to None.
            **kwargs: Additional keyword arguments to pass to the Kubernetes API.

        Raises:
            KernelDeleteError: If there is an error deleting the kernel from the API.

        Returns:
            None: The method returns None if the kernel is successfully deleted or if it doesn't exist.
        """
        timeout = timeout or self.timeout

        try:
            kernel = await self.aget_kernel_by_id(kernel_id=kernel_id, namespace=namespace, timeout=timeout)
            if kernel is None:
                return None

            partial_func = partial(
                self.api_instance.delete_namespaced_custom_object,
                group=self.group,
                version=self.version,
                plural=self.plural,
                namespace=kernel.kernel_namespace,
                name=kernel.kernel_name,
                _request_timeout=timeout,
                **kwargs,
            )

            await self.loop.run_in_executor(self.executor, partial_func)
        except KernelRetrieveError:
            return None
        except ApiException as e:
            self.logger.exception(traceback.format_exc())
            error_msg = f"Error deleting kernel: {e.status}\n{e.reason}"
            raise KernelDeleteError(error_msg) from e

    async def _wait_for_kernel_ready(self, kernel_id: str, namespace: str, timeout=60, **kwargs) -> bool:
        """Wait for a kernel to be ready by polling its status.

        This method continuously polls the kernel status until it is ready or times out.
        It checks the kernel's ready status every second up to the specified timeout.

        Args:
            kernel_id (str): The ID of the kernel to wait for
            namespace (str): The namespace where the kernel is running
            timeout (int, optional): Maximum time in seconds to wait. Defaults to 60.
            **kwargs: Additional arguments passed to aget_kernel_by_id

        Returns:
            bool: True if kernel becomes ready within timeout, False otherwise

        Note:
            The method will return False if any exceptions occur while polling the kernel status
            or if the timeout is reached before the kernel becomes ready.
        """
        start_time = time.time()
        while True:
            try:
                kernel = await self.aget_kernel_by_id(
                    kernel_id=kernel_id,
                    namespace=namespace,
                    timeout=timeout,
                    **kwargs,
                )

                if kernel is not None and kernel.ready:
                    return True

                if time.time() - start_time > timeout:
                    error_msg = f"Timeout waiting for kernel-id {kernel_id} in namespace {namespace} to be ready"
                    self.logger.warning(error_msg)

                    return False

                await asyncio.sleep(1)

            except Exception as e:
                self.logger.exception(traceback.format_exc())
                error_msg = f"Error retrieving kernel {kernel_id} in namespace {namespace}"
                raise KernelRetrieveError(error_msg) from e

    def _deserialize(self, data, klass):
        """Deserializes dict, list, str into an object.

        Args:
            data: dict, list or str.
            klass: class literal, or string of class name.

        Returns:
            object.
        """
        if data is None:
            return None

        if klass == "file":
            return self.__deserialize_file(data)

        if type(klass) == str:  # noqa: E721
            if klass.startswith("list["):
                sub_kls = re.match(r"list\[(.*)\]", klass).group(1)
                return [self._deserialize(sub_data, sub_kls) for sub_data in data]

            if klass.startswith("dict("):
                sub_kls = re.match(r"dict\(([^,]*), (.*)\)", klass).group(2)
                return {k: self._deserialize(v, sub_kls) for k, v in six.iteritems(data)}

            # convert str to class
            if klass in self.NATIVE_TYPES_MAPPING:
                klass = self.NATIVE_TYPES_MAPPING[klass]
            else:
                try:
                    klass = getattr(jkmodels, klass)
                except AttributeError:
                    klass = getattr(kubernetes.client.models, klass)

        if klass in self.PRIMITIVE_TYPES:
            return self.__deserialize_primitive(data, klass)
        if isinstance(klass, type) and klass is object:
            return self.__deserialize_object(data)
        if isinstance(klass, type) and klass is datetime.date:
            return self.__deserialize_date(data)
        if isinstance(klass, type) and klass is datetime.datetime:
            return self.__deserialize_datetime(data)

        return self.__deserialize_model(data, klass)

    def __deserialize_file(self, response):
        """Deserializes body to file

        Saves response body into a file in a temporary folder,
        using the filename from the `Content-Disposition` header if provided.

        Args:
            response: RESTResponse.

        Returns:
            file path.
        """
        fd, path = tempfile.mkstemp(dir=self.configuration.temp_folder_path)
        os.close(fd)
        os.remove(path)

        content_disposition = response.getheader("Content-Disposition")
        if content_disposition:
            filename = re.search(r'filename=[\'"]?([^\'"\s]+)[\'"]?', content_disposition).group(1)
            path = os.path.join(os.path.dirname(path), filename)

        with open(path, "wb") as f:
            f.write(response.data)

        return path

    def __deserialize_primitive(self, data, klass):
        """Deserializes string to primitive type.

        Args:
            data: str.
            klass: class literal.

        Returns:
            int, long, float, str, bool.
        """
        try:
            return klass(data)
        except UnicodeEncodeError:
            return six.text_type(data)
        except TypeError:
            return data

    def __deserialize_object(self, value):
        """Return an original value.

        Returns:
            object.
        """
        return value

    def __deserialize_date(self, string):
        """Deserializes string to date.

        Args:
            string: str.

        Returns:
            date.

        Raises:
            ValueError: If string cannot be parsed as date.
        """
        try:
            return parse(string).date()
        except ImportError:
            return string
        except ValueError as e:
            error_msg = f"Failed to parse `{string}` as date object"
            raise ValueError(error_msg) from e

    def __deserialize_datetime(self, string):
        """Deserializes string to datetime.

        The string should be in iso8601 datetime format.

        Args:
            string: str.

        Returns:
            datetime.

        Raises:
            ValueError: If string cannot be parsed as datetime.
        """
        try:
            return parse(string)
        except ImportError:
            return string
        except ValueError as e:
            error_msg = f"Failed to parse `{string}` as datetime object"
            raise ValueError(error_msg) from e

    def __deserialize_model(self, data, klass):
        """Deserializes list or dict to model.

        Args:
            data: dict, list.
            klass: class literal.

        Returns:
            model object.
        """
        if not klass.openapi_types and not hasattr(klass, "get_real_child_model"):
            return data

        kwargs = {}
        if data is not None and klass.openapi_types is not None and isinstance(data, (list, dict)):  # noqa: UP038
            for attr, attr_type in six.iteritems(klass.openapi_types):
                if klass.attribute_map[attr] in data:
                    value = data[klass.attribute_map[attr]]
                    kwargs[attr] = self._deserialize(value, attr_type)

        instance = klass(**kwargs)

        if hasattr(instance, "get_real_child_model"):
            klass_name = instance.get_real_child_model(data)
            if klass_name:
                instance = self._deserialize(data, klass_name)
        return instance
