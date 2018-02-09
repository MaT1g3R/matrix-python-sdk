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

    @property
    def global_listeners(self):
        return self.listeners[ListenerType.GLOBAL]

    @property
    def presence_listeners(self):
        return self.listeners[ListenerType.PRESENCE]

    @property
    def invite_listeners(self):
        return self.listeners[ListenerType.INVITE]

    @property
    def left_listeners(self):
        return self.listeners[ListenerType.LEAVE]

    @property
    def ephemeral_listeners(self):
        return self.listeners[ListenerType.EPHEMERAL]

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
            callback (func(roomchunk)): Callback called when an event arrives.
            event_type (str): The event_type to filter for.
            listener_type (ListenerType): The type of the listener.
                                          Defualts to all types.

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

    def add_global_listener(self, callback, event_type=None) -> Listener:
        """
        Add a global listner that will send a callback on all events.
        Args:
            callback: The call back coroutine.
            event_type: The event type to filter for.

        Returns:
            The listener created.

        """
        return self.add_listener(
            callback,
            event_type=event_type,
            listener_type=ListenerType.GLOBAL
        )

    def remove_global_listener(self, uid):
        """
        Remove global listener with give uid.
        Args:
            uid (uuid.UUID): Unique id of the listener to remove.
        """
        self.remove_listener(uid, ListenerType.GLOBAL)

    def add_presence_listener(self, callback) -> Listener:
        """ Add a presence listener that will send a callback when the client receives
        a presence update.

        Args:
            callback (func(roomchunk)): Callback called when a presence update arrives.

        Returns:
            The listener created.
        """
        return self.add_listener(callback, listener_type=ListenerType.PRESENCE)

    def remove_presence_listener(self, uid):
        """ Remove presence listener with given uid

        Args:
            uuid.UUID: Unique id of the listener to remove
        """
        self.remove_listener(uid, ListenerType.PRESENCE)

    def add_ephemeral_listener(self, callback, event_type=None) -> Listener:
        """ Add an ephemeral listener that will send a callback when the client recieves
        an ephemeral event.

        Args:
            callback (func(roomchunk)): Callback called when an ephemeral event arrives.
            event_type (str): The event_type to filter for.

        Returns:
            The listener created.
        """
        return self.add_listener(
            callback,
            listener_type=ListenerType.EPHEMERAL,
            event_type=event_type
        )

    def remove_ephemeral_listener(self, uid):
        """ Remove ephemeral listener with given uid.

        Args:
            uuid.UUID: Unique id of the listener to remove.
        """
        self.remove_listener(uid, ListenerType.EPHEMERAL)

    def add_invite_listener(self, callback) -> Listener:
        """ Add a listener that will send a callback when the client receives
        an invite.

        Args:
            callback (func(room_id, state)): Callback called when an invite arrives.

        Returns:
            The listener created.
        """
        return self.add_listener(callback, listener_type=ListenerType.INVITE)

    def add_leave_listener(self, callback) -> Listener:
        """ Add a listener that will send a callback when the client has left a room.

        Args:
            callback (func(room_id, room)): Callback called when the client
            has left a room.

        Returns:
            The listener created.
        """
        return self.add_listener(callback, listener_type=ListenerType.LEAVE)

    def start_listener(self, timeout_ms=30000):
        """ Start a listener thread to listen for events in the background.

        Args:
            timeout_ms(int): How long to poll the Home Server for before
               retrying.
        """
        self._create_task(self.consume_events())
        return super().start_listener(timeout_ms)

    async def consume_events(self):
        while self.should_listen:
            event = await self.event_queue.get()
            if event.type == ListenerType.GLOBAL:
                for listener in self.global_listeners:
                    if (
                            listener.event_type is None or
                            listener.event_type == event.event['type']
                    ):
                        self._create_task(listener(event.event))
            elif event.type == ListenerType.PRESENCE:
                for listener in self.presence_listeners:
                    self._create_task(listener(event.event))
            elif event.type == ListenerType.INVITE:
                for listener in self.invite_listeners:
                    self._create_task(listener(event.room_id, event.event))
            elif event.type == ListenerType.LEAVE:
                for listener in self.left_listeners:
                    self._create_task(listener(event.room_id, event.event))
            elif event.type == ListenerType.EPHEMERAL:
                for listener in self.ephemeral_listeners:
                    if (
                            listener.event_type is None or
                            listener.event_type == event.event['type']
                    ):
                        self._create_task(listener(event.event))
