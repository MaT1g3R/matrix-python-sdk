# -*- coding: utf-8 -*-
# Copyright 2015 OpenMarket Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from asyncio import Queue, ensure_future, get_event_loop, sleep, Future

from .api import MatrixHttpApi
from .enums import CACHE, ListenerType
from .errors import MatrixRequestError, MatrixUnexpectedResponse
from .event import InvitedRoom, Event, LeftRoom, Timeline, JoinedRoom
from .listener import ListenerClientMixin
from .room import Room
from .user import User

logger = logging.getLogger(__name__)


class MatrixBaseClient(object):
    """
    The client API for Matrix. For the raw HTTP calls, see MatrixHttpApi.

    Args:
        base_url (str):
            The url of the HS preceding /_matrix.
            e.g. (ex: https://matrix.org)
        token (Optional[str]):
            If you have an access token supply it here.
        user_id (Optional[str]):
            You must supply the user_id
            (as obtained when initially logging in to obtain the token)
            if supplying a token; otherwise, ignored.
        valid_cert_check (bool):
            Check the homeservers certificate on connections?
        sync_filter_limit (int):
            The timeline event count limit for each sync.
        cache_level (CACHE):
            One of CACHE.NONE, CACHE.SOME, or CACHE.ALL
            (defined in enums).
        loop (Optional[BaseEventLoop]):
            Optional. Asyncio event loop.

    Returns:
        `MatrixBaseClient`

    Raises:
        `MatrixRequestError`, `ValueError`

    Examples:

        Create a new user and send a message::

            async def main():
                client = MatrixClient("https://matrix.org")
                token = await client.register_with_password(
                            username="foobar", password="monkey"
                        )
                room = await client.create_room("myroom")
                await room.send_image(file_like_object)
    """

    def __init__(self, base_url, token=None, user_id=None,
                 valid_cert_check=True, sync_filter_limit=20,
                 cache_level=CACHE.ALL, loop=None):
        """
        reate a new Matrix Client object.

        Args:
            base_url (str):
                The url of the HS preceding /_matrix.
                e.g. (ex: https://matrix.org)
            token (Optional[str]):
                If you have an access token supply it here.
            user_id (Optional[str]):
                You must supply the user_id
                (as obtained when initially logging in to obtain the token)
                if supplying a token; otherwise, ignored.
            valid_cert_check (bool):
                Check the homeservers certificate on connections?
            sync_filter_limit (int):
                The timeline event count limit for each sync.
            cache_level (CACHE):
                One of CACHE.NONE, CACHE.SOME, or CACHE.ALL
                (defined in enums).
            loop (Optional[BaseEventLoop]):
                Optional. Asyncio event loop.
        Returns:
            MatrixBaseClient

        Raises:
            MatrixRequestError, ValueError
        """
        if token is not None and user_id is None:
            raise ValueError("must supply user_id along with token")
        self.loop = loop or get_event_loop()
        self.api = MatrixHttpApi(base_url, token, loop=loop)
        self.api.validate_certificate(valid_cert_check)
        self.event_queue = Queue(loop=self.loop)
        self.room_event_queue = Queue(loop=self.loop)
        if isinstance(cache_level, CACHE):
            self._cache_level = cache_level
        else:
            raise ValueError(
                "cache_level must be one of CACHE.NONE, CACHE.SOME, CACHE.ALL"
            )

        self.sync_token = None
        self.sync_filter = (
                '{ "room": { "timeline" : { "limit" : %i } } }'
                % sync_filter_limit
        )
        self.sync_task = None
        self.should_listen = False

        # Time to wait before attempting a /sync request after failing.
        self.bad_sync_timeout_limit = 60 * 60
        self.rooms = {
            # room_id: Room
        }
        self.token = token
        self.user_id = user_id
        self.logger = logger

    async def on_exception(self, e):
        """
        Default exception handling for exceptions during sync.
        This is expected to be overwritten in a subclass.

        Args:
            e (Exception): The exception raised.
        """
        logger.exception(f"Exception thrown during sync: {e}")

    async def register_as_guest(self) -> str:
        """
        Register a guest account on this HS.

        Note: HS must have guest registration enabled.

        Returns:
            str: Access Token
        Raises:
            MatrixRequestError
        """
        response = await self.api.register(kind='guest')
        return await self._post_registration(response)

    async def register_with_password(self, username, password) -> str:
        """
        Register for a new account on this HS.

        Args:
            username (str): Account username
            password (str): Account password

        Returns:
            str: Access Token

        Raises:
            MatrixRequestError
        """
        response = await self.api.register(
            {
                "auth": {"type": "m.login.dummy"},
                "username": username,
                "password": password
            }
        )
        return await self._post_registration(response)

    async def _post_registration(self, response) -> str:
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        await self.sync()
        return self.token

    async def login_with_password_no_sync(self, username, password) -> str:
        """
        Login to the homeserver.

        Args:
            username (str): Account username
            password (str): Account password

        Returns:
            str: Access token

        Raises:
            MatrixRequestError
        """
        response = await self.api.login(
            "m.login.password", user=username, password=password
        )
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        return self.token

    async def login_with_password(self, username, password, limit=10) -> str:
        """
        Login to the homeserver.

        Args:
            username (str): Account username
            password (str): Account password
            limit (int): Deprecated. How many messages to return when syncing.
                This will be replaced by a filter API in a later release.

        Returns:
            str: Access token

        Raises:
            MatrixRequestError
        """
        token = await self.login_with_password_no_sync(username, password)

        # Limit Filter
        self.sync_filter = '{ "room": { "timeline" : { "limit" : %i } } }' % limit
        await self.sync()
        return token

    async def logout(self):
        """ Logout from the homeserver."""
        await self.api.logout()

    async def create_room(self, alias=None, is_public=False,
                          invitees=()) -> Room:
        """ Create a new room on the homeserver.

        Args:
            alias (str): The canonical_alias of the room.
            is_public (bool):  The public/private visibility of the room.
            invitees (str[]): A set of user ids to invite into the room.

        Returns:
            Room

        Raises:
            MatrixRequestError
        """
        response = await self.api.create_room(alias, is_public, invitees)
        return self._mkroom(response["room_id"])

    async def join_room(self, room_id_or_alias) -> Room:
        """
        Join a room.

        Args:
            room_id_or_alias (str): Room ID or an alias.

        Returns:
            Room

        Raises:
            MatrixRequestError
        """
        response = await self.api.join_room(room_id_or_alias)
        room_id = (
            response["room_id"] if "room_id" in response else room_id_or_alias
        )
        return self._mkroom(room_id)

    async def _listen_forever(self, timeout_ms=30000):
        """
        Keep listening for events forever.

        Args:
            timeout_ms (int):
                How long to poll the Home Server for before retrying.
        """
        bad_sync_timeout = 5000
        self.should_listen = True
        while self.should_listen:
            try:
                await self.sync(timeout_ms)
                bad_sync_timeout = 5
            except MatrixRequestError as e:
                logger.warning("A MatrixRequestError occured during sync.")
                if e.code >= 500:
                    logger.warning(
                        "Problem occured serverside. Waiting %i seconds",
                        bad_sync_timeout)
                    await sleep(bad_sync_timeout)
                    bad_sync_timeout = min(bad_sync_timeout * 2,
                                           self.bad_sync_timeout_limit)
                else:
                    self.create_task(self.on_exception(e))
            except Exception as e:
                self.create_task(self.on_exception(e))

    def start_client(self, timeout_ms=30000):
        """
        Start the client to listen for events.

        Args:
            timeout_ms(int):
                How long to poll the Home Server for before retrying.
        """
        task = self.create_task(
            self._listen_forever(timeout_ms)
        )
        self.sync_task = task
        self.should_listen = True
        self.loop.run_forever()

    def stop_client(self):
        """ Stop the client from listening event."""
        if self.sync_task:
            self.should_listen = False
            self.sync_task = None
            self.loop.stop()

    async def upload(self, content: bytes, content_type: str):
        """
        Upload content to the home server and recieve a MXC url.

        Args:
            content (bytes): The data of the content.
            content_type (str): The mimetype of the content.

        Raises:
            MatrixUnexpectedResponse: If the homeserver gave a strange response
            MatrixRequestError: If the upload failed for some reason.
        """
        try:
            response = await self.api.media_upload(content, content_type)
            if "content_uri" in response:
                return response["content_uri"]
            else:
                raise MatrixUnexpectedResponse(
                    "The upload was successful, but content_uri wasn't found."
                )
        except MatrixRequestError as e:
            raise MatrixRequestError(
                code=e.code,
                content="Upload failed: %s" % e
            )

    def _mkroom(self, room_id):
        self.rooms[room_id] = Room(self, room_id)
        return self.rooms[room_id]

    def _process_state_event(self, state_event, current_room):
        etype = state_event.type
        if not etype:
            return  # ignore event
        econtent = state_event.content
        # Don't keep track of room state if caching turned off
        if self._cache_level != CACHE.NONE:
            if etype == "m.room.name":
                current_room.name = econtent.get("name")
            elif etype == "m.room.canonical_alias":
                current_room.canonical_alias = econtent.get("alias")
            elif etype == "m.room.topic":
                current_room.topic = econtent.get("topic")

            elif etype == "m.room.aliases":
                current_room.aliases = econtent.get("aliases")

            elif etype == "m.room.member" and self._cache_level == CACHE.ALL:
                # tracking room members can be large e.g. #matrix:matrix.org
                if econtent["membership"] == "join":
                    current_room._mkmembers(User(
                        self.api,
                        state_event.state_key,
                        econtent.get("displayname")
                    ))
                elif econtent["membership"] \
                        in {"leave", "kick", "invite"}:
                    current_room._rmmembers(state_event.state_key)

        self.room_event_queue.put_nowait((state_event, current_room))

    async def sync(self, timeout_ms=30000):
        """
        Preforms a sync action.

        Args:
            timeout_ms(int):
                How long to poll the Home Server for before retrying.
        """
        # TODO: Deal with left rooms
        response = await self.api.sync(self.sync_token, timeout_ms,
                                       filter=self.sync_filter)
        self.sync_token = response["next_batch"]

        for presence_update in response['presence']['events']:
            self.event_queue.put_nowait(Event(
                **presence_update,
                listener_type=ListenerType.PRESENCE
            ))

        for room_id, invite_room in response['rooms']['invite'].items():
            invite_states = [
                Event.from_dict(x)
                for x in invite_room['invite_state'].get('events', [])
            ]
            self.event_queue.put_nowait(InvitedRoom(
                room_id=room_id,
                invite_states=invite_states
            ))

        for room_id, left_room in response['rooms']['leave'].items():
            left_states = [
                Event.from_dict(x) for x in left_room.get('events', [])
            ]
            timeline = left_room.get('timeline')
            timeline_obj = Timeline.from_dict(timeline) if timeline else None
            self.event_queue.put_nowait(LeftRoom(
                room_id=room_id,
                left_states=left_states,
                timeline=timeline_obj
            ))
            if room_id in self.rooms:
                del self.rooms[room_id]

        for room_id, sync_room in response['rooms']['join'].items():
            sync_room['room_id'] = room_id
            joined_room = JoinedRoom.from_dict(sync_room)
            if room_id not in self.rooms:
                # TODO: don't keep track of joined rooms for self._cache_level==CACHE.NONE
                self._mkroom(room_id)
            room = self.rooms[room_id]
            room.prev_batch = joined_room.timeline.prev_batch

            for event in joined_room.state:
                event.listener_type = ListenerType.STATE
                self._process_state_event(event, room)

            for event in joined_room.timeline.events:
                event.listener_type = ListenerType.GLOBAL
                self.room_event_queue.put_nowait((event, room))
                self.event_queue.put_nowait(event)

            for event in joined_room.ephemeral:
                event.listener_type = ListenerType.EPHEMERAL
                self.room_event_queue.put_nowait((event, room))
                self.event_queue.put_nowait(event)

    def get_user(self, user_id) -> User:
        """
        Return a User by their id.

        NOTE: This function only returns a user object, it does not verify
            the user with the Home Server.

        Args:
            user_id (str): The matrix user id of a user.
        """

        return User(self.api, user_id)

    async def remove_room_alias(self, room_alias) -> bool:
        """
        Remove mapping of an alias

        Args:
            room_alias(str): The alias to be removed.

        Returns:
            bool: True if the alias is removed, False otherwise.
        """
        try:
            await self.api.remove_room_alias(room_alias)
            return True
        except MatrixRequestError:
            return False

    def create_task(self, coro_or_future) -> Future:
        """
        Create/Adds a task to the event loop that the client is
        running on.

        Args:
            coro_or_future (Union[Coroutine, Awaitable, Future]):
                Warp a coroutine or an awaitable in a future. If it
                is a future already, return it directly.

        Returns:
            Future: The future object created/passed in as argument.

        See Also:
            asyncio.ensure_future
        """
        return ensure_future(coro_or_future, loop=self.loop)


class MatrixListenerClient(ListenerClientMixin, MatrixBaseClient):
    """
    The client API for Matrix. For the raw HTTP calls, see MatrixHttpApi.
    This class also implements listener functionalities.

    Args:
        see `MatrixBaseClient`
    Returns:
        `MatrixListenerClient`

    Raises:
        `MatrixRequestError`, `ValueError`

    Examples:

        Send a message with an already logged in user::

            async def main():
                client = MatrixListenerClient(
                    "https://matrix.org",
                    token="foobar",
                    user_id="@foobar:matrix.org"
                )
                await client.sync() # NB: Initial sync
                rooms = client.rooms  # NB: From initial sync
                client.add_listener(func)  # NB: event stream callback
                client.add_room_listener(func, rooms[0].room_id) # NB: callbacks just for this room.
                room = await client.join_room("#matrix:matrix.org")
                response = await room.send_text("Hello!")
                response = await room.kick("@bob:matrix.org")

    See Also:
        `MatrixBaseClient`, `ListenerClientMixin`
    """
    pass
