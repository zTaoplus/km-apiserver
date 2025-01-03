"""Tornado handlers for kernel specs."""

from pathlib import Path

from jupyter_server.utils import ensure_async
from tornado import web

from mkm.handlers.mixins import CORSMixin


class BaseSpecHandler(CORSMixin, web.StaticFileHandler):
    """Exposes the ability to return specifications from static files"""

    @staticmethod
    def get_resource_metadata() -> tuple:
        """Returns the (resource, mime-type) for the handlers spec."""

    def initialize(self) -> None:
        """Initializes the instance of this class to serve files.

        The handler is initialized to serve files from the directory
        where this module is defined.  `path` parameter will be overridden.
        """
        web.StaticFileHandler.initialize(self, path=Path(__file__).parent.parent / "static")

    async def get(self) -> None:
        """Handler for a get on a specific handler"""
        resource_name, content_type = self.get_resource_metadata()
        self.set_header("Content-Type", content_type)
        res = web.StaticFileHandler.get(self, resource_name)
        await ensure_async(res)


class APIYamlHandler(BaseSpecHandler):
    """Exposes a YAML swagger specification"""

    @staticmethod
    def get_resource_metadata() -> tuple:
        """Get the resource metadata."""
        return "swagger.yaml", "text/x-yaml"


class SwaggerUIHandler(CORSMixin, web.RequestHandler):
    """Handler for serving Swagger UI interface"""

    async def get(self) -> None:
        """Serves the Swagger UI HTML page"""
        swagger_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
</head>
<body>
    <div id="swagger-ui"></div>
    <script>
        window.onload = function() {
            SwaggerUIBundle({
                url: "/api/swagger.yaml",
                dom_id: '#swagger-ui',
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout"
            });
        }
    </script>
</body>
</html>
        """
        self.set_header("Content-Type", "text/html")
        self.write(swagger_html)


_openapi_handlers: list[tuple] = [
    (f"/api/{APIYamlHandler.get_resource_metadata()[0]}", APIYamlHandler),
    (r"/api/docs", SwaggerUIHandler),
]
