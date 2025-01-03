import functools
from collections.abc import Awaitable, Callable

from tornado import web


def authenticated(method: Callable[..., Awaitable[None] | None]) -> Callable[..., Awaitable[None] | None]:
    @functools.wraps(method)
    def wrapper(  # type: ignore
        self: web.RequestHandler, *args, **kwargs
    ) -> Awaitable[None] | None:
        if not self.settings.get("allow_unauthenticated_access"):
            _user_in_header = self.settings.get("user_in_header")
            _current_user = self.request.headers.get(_user_in_header)
            if not _current_user:
                raise web.HTTPError(403)
        else:
            _current_user = "anonymous"

        self._current_user = _current_user
        return method(self, *args, **kwargs)

    return wrapper
