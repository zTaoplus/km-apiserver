from tornado.log import access_log, app_log, enable_pretty_logging


def setup_logging(level: str):
    access_log.setLevel(level)
    app_log.setLevel(level)
    enable_pretty_logging()
    app_log.info("Logging pretty enabled, log level: %s", level)
