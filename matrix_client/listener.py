from collections import defaultdict
from inspect import iscoroutinefunction
from uuid import uuid4

import attr

from .enums import ListenerType


@attr.s(frozen=True)
class Listener:
    callback = attr.ib()
    client = attr.ib()
    uuid = attr.ib(default=uuid4(), init=False)
    listener_type = attr.ib(type=ListenerType)
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


class ListenerClientMixin:
    def __init__(self, *args, **kwargs):
        self.listeners = defaultdict(set)
        super().__init__(*args, **kwargs)

    async def on_listener_error(self, e):
        """
        Default listener exception handler. This is expected to be
        overwritten in a subclass.
        Args:
            e: The exception raised by the listener.
        """
        self.logger.warning(str(e))

    def add_listener(self, callback, event_type=None,
                     listener_type=ListenerType.GLOBAL) -> Listener:
        """ Add a listener that will send a callback when the client recieves
        an event.

        Args:
            callback (coro(event)):  Callback called when an event arrives.
            event_type (str): The event_type to filter for.
            listener_type (ListenerType): The type of the listener.
                                          Defualts to global.
        Returns:
            The listener created.
        """
        listener = Listener(
            callback=callback,
            client=self,
            listener_type=listener_type,
            event_type=event_type
        )
        self.listeners[listener_type].add(listener)
        return listener

    def remove_listener(self, uid, listener_type=ListenerType.GLOBAL):
        """ Remove listener with given uid.

        Args:
            uuid.UUID: Unique id of the listener to remove.
            listener_type (ListenerType); The type of the listener to
                remove. Default is GLOBAL.
        """
        self.listeners[listener_type] = {
            lis for lis in
            self.listeners[listener_type] if
            lis.uuid != uid
        }

    def start_listener(self, timeout_ms=30000):
        """ Start a listener thread to listen for events in the background.

        Args:
            timeout_ms(int): How long to poll the Home Server for before
               retrying.
        """
        self.create_task(self.consume_events())
        return super().start_listener(timeout_ms)

    def dispatch_event(self, event):
        for listener in self.listeners[event.listener_type]:
            if not listener.event_type:
                self.create_task(listener(event))
            else:
                try:
                    event_type = event.type
                except AttributeError:
                    pass
                else:
                    if listener.event_type == event_type:
                        self.create_task(listener(event))

    async def consume_events(self):
        while self.should_listen:
            event = await self.event_queue.get()
            self.dispatch_event(event)
