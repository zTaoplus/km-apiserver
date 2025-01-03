from mkm.handlers.healthy_handlers import _healthy_handlers
from mkm.handlers.kernel_handlers import _kernel_handlers
from mkm.handlers.kernel_spec_handlers import _kernel_specs_handlers

default_handlers = _kernel_handlers + _kernel_specs_handlers + _healthy_handlers


__all__ = ["default_handlers"]
