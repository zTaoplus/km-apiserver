import functools
import time

from typing import Callable, TypeVar, ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


def async_timer(logger=None) -> Callable[..., Callable[P, R]]:
    """Decorator factory to measure and log the execution time of async functions."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed_time = time.time() - start_time
                if logger:
                    logger.info(f"{func.__name__} took {elapsed_time:.2f} seconds")

        return wrapper

    return decorator
