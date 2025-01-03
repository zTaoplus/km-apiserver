class BaseKernelError(Exception):
    message: str


# system based error
class KernelCreationError(BaseKernelError):
    message: str


class KernelWaitReadyTimeoutError(BaseKernelError):
    message: str = "Kernel wait for ready timeout"


class KernelRetrieveError(BaseKernelError):
    message: str = "Error getting kernel"


class KernelDeleteError(BaseKernelError):
    message: str = "Error deleting kernel"


# user operation error
class KernelNotFoundError(KernelRetrieveError):
    message: str = "Kernel not found"


class KernelExistsError(KernelCreationError):
    message: str = "Kernel already exists"


class KernelForbiddenError(KernelCreationError):
    message: str = "Kernel creation is forbidden"


class KernelResourceQuotaExceededError(KernelForbiddenError):
    message: str = "Kernel creation is forbidden. Resource quota exceeded."
