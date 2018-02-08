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
from asyncio import Queue, ensure_future, get_event_loop, sleep
from typing import NamedTuple, Optional

from .api import MatrixHttpApi
from .enums import CACHE, ListenerType
from .errors import MatrixRequestError, MatrixUnexpectedResponse
from .listener import ListenerClientMixin
from .room import Room
from .user import User

logger = logging.getLogger(__name__)


class Event(NamedTuple):
    type: ListenerType
    event: dict
    room_id: Optional[str] = None


class MatrixBaseClient(object):
    """
    The client API for Matrix. For the raw HTTP calls, see MatrixHttpApi.

    Args:
        base_url (str): The url of the HS preceding /_matrix.
            e.g. (ex: https://localhost:8008 )
        token (Optional[str]): If you have an access token
            supply it here.
        user_id (Optional[str]): You must supply the user_id
            (as obtained when initially logging in to obtain
            the token) if supplying a token; otherwise, ignored.
        valid_cert_check (bool): Check the homeservers
            certificate on connections?

    Returns:
        `MatrixBaseClient`

    Raises:
        `MatrixRequestError`, `ValueError`

    Examples:

        Create a new user and send a message::

            client = MatrixClient("https://matrix.org")
            token = client.register_with_password(username="foobar",
                password="monkey")
            room = client.create_room("myroom")
            room.send_image(file_like_object)

        Send a message with an already logged in user::

            client = MatrixClient("https://matrix.org", token="foobar",
                user_id="@foobar:matrix.org")
            rooms = client.get_rooms()  # NB: From initial sync
            client.add_listener(func)  # NB: event stream callback
            rooms[0].add_listener(func)  # NB: callbacks just for this room.
            room = client.join_room("#matrix:matrix.org")
            response = room.send_text("Hello!")
            response = room.kick("@bob:matrix.org")

        Incoming event callbacks (scopes)::

            def user_callback(user, incoming_event):
                pass

            def room_callback(room, incoming_event):
                pass

            def global_callback(incoming_event):
                pass
    """

    def __init__(self, base_url, token=None, user_id=None,
                 valid_cert_check=True, sync_filter_limit=20,
                 cache_level=CACHE.ALL, loop=None):
        """ Create a new Matrix Client object.

        Args:
            base_url (str): The url of the HS preceding /_matrix.
                e.g. (ex: https://localhost:8008 )
            token (str): Optional. If you have an access token
                supply it here.
            user_id (str): Optional. You must supply the user_id
                (as obtained when initially logging in to obtain
                the token) if supplying a token; otherwise, ignored.
            valid_cert_check (bool): Check the homeservers
                certificate on connections?
            cache_level (CACHE): One of CACHE.NONE, CACHE.SOME, or
                CACHE.ALL(defined in module namespace).
            loop (BaseEventLoop): Optional. Asyncio event loop.

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
        if self.token:
            self._create_task(self.sync())

    async def on_exception(self, e):
        """
        Default exception handling for exceptions during sync.
        Args:
            e: The exception raised.
        """
        logger.exception(f"Exception thrown during sync: {e}")

    async def register_as_guest(self):
        """ Register a guest account on this HS.
        Note: HS must have guest registration enabled.
        Returns:
            str: Access Token
        Raises:
            MatrixRequestError
        """
        response = await self.api.register(kind='guest')
        return await self._post_registration(response)

    async def register_with_password(self, username, password):
        """ Register for a new account on this HS.

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

    async def _post_registration(self, response):
        self.user_id = response["user_id"]
        self.token = response["access_token"]
        self.hs = response["home_server"]
        self.api.token = self.token
        await self.sync()
        return self.token

    async def login_with_password_no_sync(self, username, password):
        """ Login to the homeserver.

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

    async def login_with_password(self, username, password, limit=10):
        """ Login to the homeserver.

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
        """ Logout from the homeserver.
        """
        await self.api.logout()
        self.loop.stop()

    async def create_room(self, alias=None, is_public=False, invitees=()):
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

    async def join_room(self, room_id_or_alias):
        """ Join a room.

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

    async def listen_forever(self, timeout_ms=30000):
        """ Keep listening for events forever.

        Args:
            timeout_ms (int): How long to poll the Home Server for before
               retrying.
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
                    raise e
            except Exception as e:
                self._create_task(self.on_exception(e))

    def start_listener(self, timeout_ms=30000):
        """ Start a listener thread to listen for events in the background.

        Args:
            timeout_ms(int): How long to poll the Home Server for before
               retrying.
        """
        task = self._create_task(
            self.listen_forever(timeout_ms)
        )
        self.sync_task = task
        self.should_listen = True
        return task

    def stop_listener(self):
        """ Stop listener thread running in the background
        """
        if self.sync_task:
            self.should_listen = False
            self.sync_task = None
            self.loop.stop()

    async def upload(self, content, content_type):
        """ Upload content to the home server and recieve a MXC url.

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
        if "type" not in state_event:
            return  # Ignore event
        etype = state_event["type"]

        # Don't keep track of room state if caching turned off
        if self._cache_level != CACHE.NONE:
            if etype == "m.room.name":
                current_room.name = state_event["content"].get("name", None)
            elif etype == "m.room.canonical_alias":
                current_room.canonical_alias = state_event["content"].get(
                    "alias")
            elif etype == "m.room.topic":
                current_room.topic = state_event["content"].get("topic", None)
            elif etype == "m.room.aliases":
                current_room.aliases = state_event["content"].get("aliases",
                                                                  None)
            elif etype == "m.room.member" and self._cache_level == CACHE.ALL:
                # tracking room members can be large e.g. #matrix:matrix.org
                if state_event["content"]["membership"] == "join":
                    current_room._mkmembers(
                        User(self.api,
                             state_event["state_key"],
                             state_event["content"].get("displayname", None))
                    )
                elif state_event["content"]["membership"] in (
                        "leave", "kick", "invite"):
                    current_room._rmmembers(state_event["state_key"])

        for listener in current_room.state_listeners:
            if (
                    listener.event_type is None or
                    listener.event_type == state_event['type']
            ):
                self._create_task(listener(state_event))

    async def sync(self, timeout_ms=30000):
        # TODO: Deal with left rooms
        response = await self.api.sync(self.sync_token, timeout_ms,
                                       filter=self.sync_filter)
        self.sync_token = response["next_batch"]

        for presence_update in response['presence']['events']:
            self.event_queue.put_nowait(
                Event(
                    event=presence_update,
                    type=ListenerType.PRESENCE
                )
            )

        for room_id, invite_room in response['rooms']['invite'].items():
            self.event_queue.put_nowait(
                Event(
                    type=ListenerType.INVITE,
                    event=invite_room['invite_state'],
                    room_id=room_id
                )
            )

        for room_id, left_room in response['rooms']['leave'].items():
            self.event_queue.put_nowait(
                Event(
                    type=ListenerType.LEAVE,
                    event=left_room,
                    room_id=room_id
                )
            )
            if room_id in self.rooms:
                del self.rooms[room_id]

        for room_id, sync_room in response['rooms']['join'].items():
            if room_id not in self.rooms:
                # TODO: don't keep track of joined rooms for self._cache_level==CACHE.NONE
                self._mkroom(room_id)
            room = self.rooms[room_id]
            room.prev_batch = sync_room["timeline"]["prev_batch"]

            for event in sync_room["state"]["events"]:
                event['room_id'] = room_id
                self._process_state_event(event, room)

            for event in sync_room["timeline"]["events"]:
                event['room_id'] = room_id
                room._put_event(event)
                self.event_queue.put_nowait(
                    Event(
                        type=ListenerType.GLOBAL,
                        event=event
                    )
                )

            for event in sync_room['ephemeral']['events']:
                event['room_id'] = room_id
                room._put_ephemeral_event(event)

                self.event_queue.put_nowait(
                    Event(
                        type=ListenerType.EPHEMERAL,
                        event=event
                    )
                )

    def get_user(self, user_id):
        """ Return a User by their id.

        NOTE: This function only returns a user object, it does not verify
            the user with the Home Server.

        Args:
            user_id (str): The matrix user id of a user.
        """

        return User(self.api, user_id)

    async def remove_room_alias(self, room_alias):
        """Remove mapping of an alias

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

    def _create_task(self, coro):
        return ensure_future(coro, loop=self.loop)


class MatrixListenerClient(ListenerClientMixin, MatrixBaseClient):
    pass
