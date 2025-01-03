from tornado.log import access_log, app_log, enable_pretty_logging
from tornado.options import options
from mkm.jupyter_kernel_client.log import client_logger


def setup_logging(level: str):
    # Set the log level from the input parameter
    options.logging = level

    # Enable pretty logging for app log access_log and client_logger
    enable_pretty_logging(options, logger=app_log)
    enable_pretty_logging(options, logger=access_log)
    enable_pretty_logging(options, logger=client_logger)
    app_log.info("Logging pretty enabled, log level: %s", level)
