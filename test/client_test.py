import asyncio
import pytest
import responses
from responses import RequestsMock
import json
from copy import deepcopy
from matrix_client.client import Room, User, CACHE
from matrix_client.api import MATRIX_V2_API_PATH

from .mock_client import MockClient as MatrixClient
from . import response_examples
try:
    from urllib import quote
except ImportError:
    from urllib.parse import quote

HOSTNAME = "http://example.com"


pytestmark = pytest.mark.asyncio

async def test_create_client():
    await MatrixClient("http://example.com")


async def test_sync_token():
    client = await MatrixClient("http://example.com")
    assert client.sync_token is None
    client.sync_token = "FAKE_TOKEN"
    assert client.sync_token == "FAKE_TOKEN"


async def test__mkroom():
    client = await MatrixClient("http://example.com")

    roomId = "!UcYsUzyxTGDxLBEvLz:matrix.org"
    goodRoom = client._mkroom(roomId)

    assert isinstance(goodRoom, Room)
    assert goodRoom.room_id is roomId

    with pytest.raises(ValueError):
        client._mkroom("BAD_ROOM:matrix.org")
        client._mkroom("!BAD_ROOMmatrix.org")
        client._mkroom("!BAD_ROOM::matrix.org")


async def test_get_rooms():
    client = await MatrixClient("http://example.com")
    rooms = client.rooms
    assert isinstance(rooms, dict)
    assert len(rooms) == 0

    client = MatrixClient("http://example.com")

    client._mkroom("!abc:matrix.org")
    client._mkroom("!def:matrix.org")
    client._mkroom("!ghi:matrix.org")

    rooms = client.rooms
    assert isinstance(rooms, dict)
    assert len(rooms) == 3


async def test_bad_state_events():
    client = await MatrixClient("http://example.com")
    room = client._mkroom("!abc:matrix.org")

    ev = {
        "tomato": False
    }

    client._process_state_event(ev, room)


async def test_state_event():
    client = await MatrixClient("http://example.com")
    room = client._mkroom("!abc:matrix.org")

    room.name = False
    room.topic = False
    room.aliases = False

    ev = {
        "type": "m.room.name",
        "content": {}
    }

    client._process_state_event(ev, room)
    assert room.name is None

    ev["content"]["name"] = "TestName"
    client._process_state_event(ev, room)
    assert room.name is "TestName"

    ev["type"] = "m.room.topic"
    client._process_state_event(ev, room)
    assert room.topic is None

    ev["content"]["topic"] = "TestTopic"
    client._process_state_event(ev, room)
    assert room.topic is "TestTopic"

    ev["type"] = "m.room.aliases"
    client._process_state_event(ev, room)
    assert room.aliases is None

    aliases = ["#foo:matrix.org", "#bar:matrix.org"]
    ev["content"]["aliases"] = aliases
    client._process_state_event(ev, room)
    assert room.aliases is aliases

    # test member join event
    ev["type"] = "m.room.member"
    ev["content"] = {'membership': 'join', 'displayname': 'stereo'}
    ev["state_key"] = "@stereo:xxx.org"
    client._process_state_event(ev, room)
    assert len(room._members) == 1
    assert room._members[0].user_id == "@stereo:xxx.org"
    # test member leave event
    ev["content"]['membership'] = 'leave'
    client._process_state_event(ev, room)
    assert len(room._members) == 0


async def test_get_user():
    client = await MatrixClient("http://example.com")

    assert isinstance(client.get_user("@foobar:matrix.org"), User)

    with pytest.raises(ValueError):
        client.get_user("badfoobar:matrix.org")
        client.get_user("@badfoobarmatrix.org")
        client.get_user("@badfoobar:::matrix.org")


async def test_get_download_url():
    client = await MatrixClient("http://example.com")
    real_url = "http://example.com/_matrix/media/r0/download/foobar"
    assert client.api.get_download_url("mxc://foobar") == real_url

    with pytest.raises(ValueError):
        client.api.get_download_url("http://foobar")


async def test_remove_listener():
    async def dummy_listener():
        pass

    client = await MatrixClient("http://example.com")
    handler = client.add_listener(dummy_listener)

    found_listener = False
    for listener in client.listeners:
        if listener["uid"] == handler:
            found_listener = True
            break

    assert found_listener, "listener was not added properly"

    client.remove_listener(handler)
    found_listener = False
    for listener in client.listeners:
        if listener["uid"] == handler:
            found_listener = True
            break

    assert not found_listener, "listener was not removed properly"


class TestClientRegister:

    async def test_register_as_guest(self):
        cli = await MatrixClient(HOSTNAME)

        async def sync(self):
            self._sync_called = True

        cli.__dict__[sync.__name__] = sync.__get__(cli, cli.__class__)

        register_guest_url = HOSTNAME + MATRIX_V2_API_PATH + "/register"
        response_body = json.dumps({
            'access_token': 'EXAMPLE_ACCESS_TOKEN',
            'device_id': 'guest_device',
            'home_server': 'example.com',
            'user_id': '@455:example.com'
        })
        with RequestsMock() as r:
            r.add(responses.POST, register_guest_url, body=response_body)
            await cli.register_as_guest()
            assert cli.token == cli.api.token == 'EXAMPLE_ACCESS_TOKEN'
            assert cli.hs == 'example.com'
            assert cli.user_id == '@455:example.com'
            assert cli._sync_called


async def test_get_rooms_display_name():

    def add_members(api, room, num):
        for i in range(num):
            room._mkmembers(User(api, '@frho%s:matrix.org' % i, 'ho%s' % i))

    client = await MatrixClient("http://example.com")
    client.user_id = "@frho0:matrix.org"
    room1 = client._mkroom("!abc:matrix.org")
    add_members(client.api, room1, 1)
    room2 = client._mkroom("!def:matrix.org")
    add_members(client.api, room2, 2)
    room3 = client._mkroom("!ghi:matrix.org")
    add_members(client.api, room3, 3)
    room4 = client._mkroom("!rfi:matrix.org")
    add_members(client.api, room4, 30)

    rooms = client.rooms
    assert len(rooms) == 4
    assert await room1.get_display_name() == "Empty room"
    assert await room2.get_display_name() == "ho1"
    assert await room3.get_display_name() == "ho1 and ho2"
    assert await room4.get_display_name() == "ho1 and 28 others"


async def test_presence_listener():
    client = await MatrixClient("http://example.com")
    accumulator = []

    async def dummy_callback(event):
        accumulator.append(event)

    presence_events = [
        {
            "content": {
                "avatar_url": "mxc://localhost:wefuiwegh8742w",
                "currently_active": False,
                "last_active_ago": 2478593,
                "presence": "online",
                "user_id": "@example:localhost"
            },
            "event_id": "$WLGTSEFSEF:localhost",
            "type": "m.presence"
        },
        {
            "content": {
                "avatar_url": "mxc://localhost:weaugwe742w",
                "currently_active": True,
                "last_active_ago": 1478593,
                "presence": "online",
                "user_id": "@example2:localhost"
            },
            "event_id": "$CIGTXEFREF:localhost",
            "type": "m.presence"
        },
        {
            "content": {
                "avatar_url": "mxc://localhost:wefudweg13742w",
                "currently_active": False,
                "last_active_ago": 24795,
                "presence": "offline",
                "user_id": "@example3:localhost"
            },
            "event_id": "$ZEGASEDSEF:localhost",
            "type": "m.presence"
        },
    ]
    sync_response = deepcopy(response_examples.example_sync)
    sync_response["presence"]["events"] = presence_events
    response_body = json.dumps(sync_response)
    sync_url = HOSTNAME + MATRIX_V2_API_PATH + "/sync"

    with RequestsMock() as r:
        r.add(responses.GET, sync_url, body=response_body)
        callback_uid = client.add_presence_listener(dummy_callback)
        await client.sync()
    pending = [t for t in asyncio.Task.all_tasks() if t._coro.__name__ == "dummy_callback"]
    await asyncio.gather(*pending)
    assert accumulator == presence_events
    
    with RequestsMock() as r:
        r.add(responses.GET, sync_url, body=response_body)
        client.remove_presence_listener(callback_uid)
        accumulator = []
        await client.sync()
    pending = [t for t in asyncio.Task.all_tasks() if t._coro.__name__ == "dummy_callback"]
    await asyncio.gather(*pending)
    assert accumulator == []


async def test_changing_user_power_levels():
    client = await MatrixClient(HOSTNAME)
    room_id = "!UcYsUzyxTGDxLBEvLz:matrix.org"
    room = client._mkroom(room_id)
    PL_state_path = HOSTNAME + MATRIX_V2_API_PATH + \
        "/rooms/" + quote(room_id) + "/state/m.room.power_levels"
    
    with RequestsMock() as r:
        # Code should first get current power_levels and then modify them
        r.add(responses.GET, PL_state_path,
                      json=response_examples.example_pl_event["content"])
        r.add(responses.PUT, PL_state_path,
                      json=response_examples.example_event_response)
        # Removes user from user and adds user to to users list
        assert await room.modify_user_power_levels(users={"@example:localhost": None,
                                                    "@foobar:example.com": 49})

        expected_request = deepcopy(response_examples.example_pl_event["content"])
        del expected_request["users"]["@example:localhost"]
        expected_request["users"]["@foobar:example.com"] = 49

        assert json.loads(r.calls[1].request.body) == expected_request


async def test_changing_default_power_level():
    client = await MatrixClient(HOSTNAME)
    room_id = "!UcYsUzyxTGDxLBEvLz:matrix.org"
    room = client._mkroom(room_id)
    PL_state_path = HOSTNAME + MATRIX_V2_API_PATH + \
        "/rooms/" + quote(room_id) + "/state/m.room.power_levels"
    
    with RequestsMock() as r:
        # Code should first get current power_levels and then modify them
        r.add(responses.GET, PL_state_path,
                      json=response_examples.example_pl_event["content"])
        r.add(responses.PUT, PL_state_path,
                      json=response_examples.example_event_response)
        assert await room.modify_user_power_levels(users_default=23)

        expected_request = deepcopy(response_examples.example_pl_event["content"])
        expected_request["users_default"] = 23

        assert json.loads(r.calls[1].request.body) == expected_request


async def test_changing_event_required_power_levels():
    client = await MatrixClient(HOSTNAME)
    room_id = "!UcYsUzyxTGDxLBEvLz:matrix.org"
    room = client._mkroom(room_id)
    PL_state_path = HOSTNAME + MATRIX_V2_API_PATH + \
        "/rooms/" + quote(room_id) + "/state/m.room.power_levels"

    with RequestsMock() as r:
        # Code should first get current power_levels and then modify them
        r.add(responses.GET, PL_state_path,
                      json=response_examples.example_pl_event["content"])
        r.add(responses.PUT, PL_state_path,
                      json=response_examples.example_event_response)
        # Remove event from events and adds new controlled event
        assert await room.modify_required_power_levels(events={"m.room.name": None,
                                                         "example.event": 51})

        expected_request = deepcopy(response_examples.example_pl_event["content"])
        del expected_request["events"]["m.room.name"]
        expected_request["events"]["example.event"] = 51

        assert json.loads(r.calls[1].request.body) == expected_request


async def test_changing_other_required_power_levels():
    client = await MatrixClient(HOSTNAME)
    room_id = "!UcYsUzyxTGDxLBEvLz:matrix.org"
    room = client._mkroom(room_id)
    PL_state_path = HOSTNAME + MATRIX_V2_API_PATH + \
        "/rooms/" + quote(room_id) + "/state/m.room.power_levels"

    with RequestsMock() as r:
        # Code should first get current power_levels and then modify them
        r.add(responses.GET, PL_state_path,
                      json=response_examples.example_pl_event["content"])
        r.add(responses.PUT, PL_state_path,
                      json=response_examples.example_event_response)
        # Remove event from events and adds new controlled event
        assert await room.modify_required_power_levels(kick=53, redact=2,
                                                 state_default=None)

        expected_request = deepcopy(response_examples.example_pl_event["content"])
        expected_request["kick"] = 53
        expected_request["redact"] = 2
        del expected_request["state_default"]

        assert json.loads(r.calls[1].request.body) == expected_request


async def test_cache():
    m_none = await MatrixClient("http://example.com", cache_level=CACHE.NONE)
    m_some = await MatrixClient("http://example.com", cache_level=CACHE.SOME)
    m_all = await MatrixClient("http://example.com", cache_level=CACHE.ALL)
    sync_url = HOSTNAME + MATRIX_V2_API_PATH + "/sync"
    room_id = "!726s6s6q:example.com"
    room_name = "The FooBar"
    sync_response = deepcopy(response_examples.example_sync)

    with pytest.raises(ValueError):
        MatrixClient("http://example.com", cache_level=1)
        MatrixClient("http://example.com", cache_level=5)
        MatrixClient("http://example.com", cache_level=0.5)
        MatrixClient("http://example.com", cache_level=-5)
        MatrixClient("http://example.com", cache_level="foo")
        MatrixClient("http://example.com", cache_level=0.0)

    sync_response["rooms"]["join"][room_id]["state"]["events"].append(
        {
            "sender": "@alice:example.com",
            "type": "m.room.name",
            "state_key": "",
            "content": {"name": room_name},
        }
    )
    
    with RequestsMock() as r:
        r.add(responses.GET, sync_url, json.dumps(sync_response))
        await m_none.sync()

    with RequestsMock() as r:
        r.add(responses.GET, sync_url, json.dumps(sync_response))
        await m_some.sync()

    with RequestsMock() as r:
        r.add(responses.GET, sync_url, json.dumps(sync_response))
        await m_all.sync()

    assert m_none.rooms[room_id].name is None
    assert m_some.rooms[room_id].name == room_name
    assert m_all.rooms[room_id].name == room_name

    assert m_none.rooms[room_id]._members == m_some.rooms[room_id]._members == []
    assert len(m_all.rooms[room_id]._members) == 1
    assert m_all.rooms[room_id]._members[0].user_id == "@alice:example.com"
