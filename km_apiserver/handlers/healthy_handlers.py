from tornado import web


class HealthHandler(web.RequestHandler):
    def get(self):
        self.write("OK")


_healthy_handlers = [(r"/health", HealthHandler)]
