import json
import traceback
from http.client import responses
from typing import ClassVar

from tornado import web


class CORSMixin:
    """
    Mixes CORS headers into tornado.web.RequestHandlers.
    """

    SETTINGS_TO_HEADERS: ClassVar[dict] = {}

    def set_default_headers(self) -> None:
        """
        Sets the CORS headers as the default for all responses.

        Disables CSP configured by the notebook package. It's not necessary
        for a programmatic API.
        """
        super().set_default_headers()
        # Add CORS headers after default if they have a non-blank value
        for settings_name, header_name in self.SETTINGS_TO_HEADERS.items():
            header_value = self.settings.get(settings_name)
            if header_value:
                self.set_header(header_name, header_value)

        # Don't set CSP: we're not serving frontend media types, only JSON
        self.clear_header("Content-Security-Policy")

    def options(self) -> None:
        """
        Override the notebook implementation to return the headers
        configured in `set_default_headers instead of the hardcoded set
        supported by the handler base class in the notebook project.
        """
        self.finish()


class JSONErrorsMixin:
    """Mixes `write_error` into tornado.web.RequestHandlers to respond with
    JSON format errors.
    """

    def write_error(self, status_code: int, **kwargs) -> None:
        """Responds with an application/json error object.

        Overrides the APIHandler.write_error in the notebook server until it
        properly sets the 'reason' field.

        Parameters
        ----------
        status_code
            HTTP status code to set
        **kwargs
            Arbitrary keyword args. Only uses `exc_info[1]`, if it exists,
            to get a `log_message`, `args`, and `reason` from a raised
            exception that triggered this method

        Examples
        --------
        {"401", reason="Unauthorized", message="Invalid auth token"}
        """
        exc_info = kwargs.get("exc_info")
        message = ""
        reason = responses.get(status_code, "Unknown HTTP Error")
        reply = {
            "reason": reason,
            "message": message,
        }
        if exc_info:
            exception = exc_info[1]
            # Get the custom message, if defined
            if isinstance(exception, web.HTTPError):
                reply["message"] = exception.log_message or message
            else:
                reply["message"] = "Unknown server error"
                reply["traceback"] = "".join(traceback.format_exception(*exc_info))

            # Construct the custom reason, if defined
            custom_reason = getattr(exception, "reason", "")
            if custom_reason:
                reply["reason"] = custom_reason

        self.set_header("Content-Type", "application/json")
        self.set_status(status_code, reason=reply["reason"])
        self.finish(json.dumps(reply))
