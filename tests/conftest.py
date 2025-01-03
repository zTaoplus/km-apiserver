import asyncio

import pytest
from tornado.platform.asyncio import AsyncIOMainLoop


@pytest.fixture(autouse=True)
def setup_asyncio():
    """Setup asyncio for tests"""
    AsyncIOMainLoop().install()
    loop = asyncio.get_event_loop_policy().new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
