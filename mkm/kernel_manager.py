import typing as t

from jupyter_client.ioloop.manager import AsyncIOLoopKernelManager
from jupyter_core.utils import run_sync
from jupyter_server.services.kernels.kernelmanager import AsyncMappingKernelManager
from tornado.log import app_log

from mkm.jupyter_kernel_client import JupyterKernelClient
from mkm.jupyter_kernel_client.excs import KernelDeleteError, KernelRetrieveError
from mkm.jupyter_kernel_client.schema import KernelModel, KernelPayload


class KubeMultiKernelManager(AsyncMappingKernelManager):
    """A kernel manager that manages multiple kernels in Kubernetes.

    This class extends AsyncMappingKernelManager to provide functionality for managing
    multiple Jupyter kernels running in Kubernetes CRDs:KernelManager. It handles kernel lifecycle
    operations like starting, stopping, and listing kernels.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the kernel manager.

        Args:
            *args: Variable length argument list passed to parent class
            **kwargs: Arbitrary keyword arguments passed to parent class
        """
        super().__init__(*args, **kwargs)
        self.client = JupyterKernelClient(logger=app_log)

    @property
    def _kernels(self):
        """Return self as the kernels container.

        Returns:
            KubeMultiKernelManager: Self reference
        """
        return self

    @property
    def kernel_info_timeout(self):
        """Return timeout value for kernel info requests.

        Returns:
            int: Timeout value in seconds
        """
        return 5

    def __restore_kernel_manager(self, kernel_info: KernelModel) -> AsyncIOLoopKernelManager:
        """Restore a kernel manager from kernel info.

        Args:
            kernel_info: Information about the kernel to restore

        Returns:
            AsyncIOLoopKernelManager: The restored kernel manager instance
        """
        km = AsyncIOLoopKernelManager(owns_kernel=False)
        km.kernel_id = kernel_info.kernel_id
        km.parent = self
        km.ready.set_result(True)
        km.load_connection_info(kernel_info.kernel_connection_info.model_dump())

        return km

    async def alist_kernel_ids(self, namespace: str | None = None) -> list[str]:
        """List IDs of all kernels in the given namespace.

        Args:
            namespace: Kubernetes namespace to list kernels from

        Returns:
            list[str]: List of kernel IDs
        """
        kernels = await self.client.alist(namespace=namespace)
        return [kernel.kernel_id for kernel in kernels]

    list_kernel_ids = run_sync(alist_kernel_ids)

    async def alist_kernels(self, namespace: str | None = None) -> list[KernelModel]:
        """List all kernels in the given namespace.

        Args:
            namespace: Kubernetes namespace to list kernels from

        Returns:
            list[KernelModel]: List of kernel models
        """
        return await self.client.alist(namespace=namespace)

    list_kernels = run_sync(alist_kernels)

    async def aremove_kernel(self, kernel_id: str, namespace: str | None = None) -> None:
        """Remove a kernel by ID.

        Args:
            kernel_id: ID of kernel to remove
            namespace: Kubernetes namespace containing the kernel
        """
        try:
            return await self.client.adelete_by_kernel_id(kernel_id, namespace=namespace)
        except KernelDeleteError:
            return

    remove_kernel = run_sync(aremove_kernel)

    async def astart_kernel(
        self,
        payload: KernelPayload,
        *,
        wait_for_ready: bool = True,
    ) -> KernelModel | None:
        """Start a new kernel asynchronously.

        Args:
            payload: Configuration for the new kernel
            wait_for_ready: Whether to wait for kernel to be ready

        Returns:
            KernelModel | None: The created kernel model if successful, None otherwise
        """
        kernel = await self.client.acreate(payload=payload, wait_for_ready=wait_for_ready)

        if kernel is None:
            return None

        self.__restore_kernel_manager(kernel)

        return kernel

    async def ashutdown_all(self, namespace: str | None = None) -> None:
        """Shutdown all kernels.

        Args:
            namespace: Kubernetes namespace containing the kernels
            now: Whether to force immediate shutdown
        """
        for kid in self.list_kernel_ids(namespace=namespace):
            await self.client.adelete_by_kernel_id(kid, namespace=namespace)

    shutdown_all = run_sync(ashutdown_all)

    async def acheck_kernel_id(self, kernel_id: str, namespace: str | None = None) -> bool:
        """Check if a kernel ID exists and is ready.

        Args:
            kernel_id: ID of kernel to check
            namespace: Kubernetes namespace containing the kernel

        Returns:
            bool: True if kernel exists and is ready, False otherwise
        """
        try:
            k = await self.client.aget_kernel_by_id(kernel_id=kernel_id, namespace=namespace)
        except KernelRetrieveError:
            return False

        return k is not None and k.ready

    check_kernel_id = run_sync(acheck_kernel_id)

    async def aget_kernel(
        self, kernel_id: str, namespace: str | None = None, *, serialize: bool = False
    ) -> AsyncIOLoopKernelManager | None:
        """Get a kernel by ID.

        Args:
            kernel_id: ID of kernel to get
            namespace: Kubernetes namespace containing the kernel
            serialize: Whether to return serialized kernel model

        Returns:
            AsyncIOLoopKernelManager | KernelModel | None: The kernel manager or model if found and ready, None otherwise
        """
        kernel = await self.client.aget_kernel_by_id(kernel_id=kernel_id, namespace=namespace)

        if not kernel.ready:
            return None

        return kernel if serialize else self.__restore_kernel_manager(kernel)

    get_kernel = run_sync(aget_kernel)

    def __setitem__(self, *args, **kwargs) -> None: ...

    def __getitem__(self, kernel_id: str) -> "AsyncIOLoopKernelManager":
        """Get a kernel by ID.

        Args:
            kernel_id: ID of kernel to get

        Returns:
            AsyncIOLoopKernelManager: The kernel manager instance
        """
        return self.get_kernel(kernel_id)

    def __contains__(self, kernel_id: str) -> bool:
        """Check if a kernel ID exists.

        Args:
            kernel_id: ID of kernel to check

        Returns:
            bool: True if kernel exists, False otherwise
        """
        try:
            return self.get_kernel(kernel_id, serialize=True) is not None
        except RuntimeError:
            return False

    def update_env(self, *, kernel_id: str, env: dict[str, str]) -> None: ...

    start_kernel = run_sync(astart_kernel)

    async def _add_kernel_when_ready(self, kernel_id: str, km, kernel_awaitable: t.Awaitable) -> None: ...
    async def cull_kernels(self): ...
    async def cull_kernel_if_idle(self, kernel_id): ...
    def initialize_culler(self): ...
    def start_watching_activity(self, kernel_id): ...
    def stop_watching_activity(self, kernel_id): ...
