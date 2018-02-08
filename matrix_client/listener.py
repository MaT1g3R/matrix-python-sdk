from enum import Enum
from inspect import iscoroutinefunction
from uuid import uuid4

import attr


class ListenerType(Enum):
    ALL = 0
    PRESENCE = 1
    INVITE = 2
    LEAVE = 3
    EPHEMERAL = 4


@attr.s(frozen=True)
class Listener:
    callback = attr.ib()
    client = attr.ib()
    uuid = attr.ib(default=uuid4(), init=False)
    listener_type = attr.ib()
    event_type = attr.ib(default=None)

    @callback.validator
    def is_coro(self, attribute, value):
        if not iscoroutinefunction(value):
            raise TypeError('callback must be a coroutine function.')

    def __eq__(self, other):
        return self.uuid == other.uuid

    def __hash__(self):
        return self.uuid.__hash__()

    async def __call__(self, *args, **kwargs):
        try:
            res = await self.callback(*args, **kwargs)
        except Exception as e:
            await self.client.on_listener_error(e)
        else:
            return res
