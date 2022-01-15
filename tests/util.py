from mock import Mock
import asyncio


def AsyncMock(*args, **kwargs):
    return Mock(*args,
                side_effect=lambda *_, **__: asyncio.sleep(0),
                **kwargs)
