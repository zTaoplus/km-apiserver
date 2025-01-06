from __future__ import annotations

import json

from jupyter_client.jsonutil import json_default
from tornado import web

from km_apiserver.jupyter_kernel_client.schema import KernelSpecName


class KernelSpecHandler(web.RequestHandler):
    def get(self):
        """Get the list of kernel specs."""

        specs = [spec.value for spec in KernelSpecName]
        self.finish(json.dumps(specs, default=json_default))


_kernel_specs_handlers = [
    (r"/api/kernelspecs", KernelSpecHandler),
]
