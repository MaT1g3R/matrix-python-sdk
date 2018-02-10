from collections import defaultdict
from inspect import iscoroutinefunction
from uuid import uuid4

import attr

from .enums import ListenerType


@attr.s(frozen=True, slots=True)
class Listener:
    callback = attr.ib()
    client = attr.ib()
    uuid = attr.ib(default=uuid4(), init=False)
    listener_type = attr.ib(type=ListenerType)
    event_type = attr.ib(default=None)
    room_id = attr.ib(default=None)

    @callback.validator
    def is_coro(self, attribute, value):
        if not iscoroutinefunction(value):
            raise TypeError('callback must be a coroutine function.')

    def __eq__(self, other):
        return self.uuid == other.uuid

    def __hash__(self):
        return hash(self.uuid)

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

        # {room_id: {listener_type: set of listeners}}
        self.room_listeners = defaultdict(lambda: defaultdict(set))
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

    def add_room_listener(self, callback, room_id, event_type=None,
                          listener_type=ListenerType.GLOBAL):
        listener = Listener(
            callback=callback,
            room_id=room_id,
            client=self,
            listener_type=listener_type,
            event_type=event_type
        )
        self.room_listeners[room_id][listener_type].add(listener)
        return listener

    def remove_listener(self, listener):
        """
        Remove listener.

        Args:
            listener: The listener to remove
        """
        self.listeners[listener.listener_type].remove(listener)

    def remove_room_listener(self, listener):
        """ Remove room listener.
        Args:
            listener: The listener to remove
        """
        if not listener.room_id:
            raise ValueError('Listener must have a room id')
        self.room_listeners[listener.room_id][listener.listener_type] \
            .remove(listener)

    def start_listener(self, timeout_ms=30000):
        """
        Start the client to listen for events. Also start
        the event consumers to dispatch events to listeners.

        Args:
            timeout_ms(int): How long to poll the Home Server for before
                             retrying.
        """
        self.create_task(self._consume_events())
        self.create_task(self._consume_room_events())
        return super().start_listener(timeout_ms)

    def _help_dispatch(self, listener, event, room):
        if room:
            self.create_task(listener(event, room))
        else:
            self.create_task(listener(event))

    def _dispatch(self, listener, event, room=None):
        if not listener.event_type:
            self._help_dispatch(listener, event, room)
        else:
            try:
                event_type = event.type
            except AttributeError:
                pass
            else:
                if listener.event_type == event_type:
                    self._help_dispatch(listener, event, room)

    async def _consume_events(self):
        while self.should_listen:
            event = await self.event_queue.get()
            for listener in self.listeners[event.listener_type]:
                self._dispatch(listener, event)

    async def _consume_room_events(self):
        while self.should_listen:
            event, room = await self.room_event_queue.get()
            for listener in (
                    self.room_listeners
                    [room.room_id][event.listener_type]
            ):
                self._dispatch(listener, event, room)
