from km_apiserver.handlers.healthy_handlers import _healthy_handlers
from km_apiserver.handlers.kernel_handlers import _kernel_handlers
from km_apiserver.handlers.kernel_spec_handlers import _kernel_specs_handlers
from km_apiserver.handlers.openapi_handlers import _openapi_handlers

# TODO: should be configurable for openapi handlers
default_handlers = _kernel_handlers + _kernel_specs_handlers + _healthy_handlers + _openapi_handlers


__all__ = ["default_handlers"]
