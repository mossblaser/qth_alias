from mock import Mock
import asyncio


def AsyncMock(event_loop, *args, **kwargs):
    return Mock(*args,
                side_effect=lambda *_, **__: asyncio.sleep(0, loop=event_loop),
                **kwargs)
