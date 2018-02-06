import responses
from responses import RequestsMock
import pytest

from .mock_client import MockClient


pytestmark = pytest.mark.asyncio


class TestTagsApi:
    cli = MockClient("http://example.com")
    user_id = "@user:matrix.org"
    room_id = "#foo:matrix.org"

    async def test_get_user_tags(self):
        tags_url = "http://example.com" \
            "/_matrix/client/r0/user/@user:matrix.org/rooms/#foo:matrix.org/tags"
        with RequestsMock() as r:
            r.add(responses.GET, tags_url, body='{}')
            await self.cli.api.get_user_tags(self.user_id, self.room_id)
            req = r.calls[0].request
            assert req.url == tags_url
            assert req.method == 'GET'

    async def test_add_user_tags(self):
        tags_url = "http://example.com" \
            "/_matrix/client/r0/user/@user:matrix.org/rooms/#foo:matrix.org/tags/foo"
        with RequestsMock() as r:
            r.add(responses.PUT, tags_url, body='{}')
            await self.cli.api.add_user_tag(self.user_id, self.room_id, "foo", body={"order": "5"})
            req = r.calls[0].request
            assert req.url == tags_url
            assert req.method == 'PUT'

    async def test_remove_user_tags(self):
        tags_url = "http://example.com" \
            "/_matrix/client/r0/user/@user:matrix.org/rooms/#foo:matrix.org/tags/foo"
        with RequestsMock() as r:
            r.add(responses.DELETE, tags_url, body='{}')
            await self.cli.api.remove_user_tag(self.user_id, self.room_id, "foo")
            req = r.calls[0].request
            assert req.url == tags_url
            assert req.method == 'DELETE'


class TestAccountDataApi:
    cli = MockClient("http://example.com")
    user_id = "@user:matrix.org"
    room_id = "#foo:matrix.org"

    async def test_set_account_data(self):
        account_data_url = "http://example.com" \
            "/_matrix/client/r0/user/@user:matrix.org/account_data/foo"
        with RequestsMock() as r:
            r.add(responses.PUT, account_data_url, body='{}')
            await self.cli.api.set_account_data(self.user_id, 'foo', {'bar': 1})
            req = r.calls[0].request
            assert req.url == account_data_url
            assert req.method == 'PUT'

    async def test_set_room_account_data(self):
        account_data_url = "http://example.com/_matrix/client/r0/user" \
            "/@user:matrix.org/rooms/#foo:matrix.org/account_data/foo"
        with RequestsMock() as r:
            r.add(responses.PUT, account_data_url, body='{}')
            await self.cli.api.set_room_account_data(self.user_id, self.room_id, 'foo', {'bar': 1})
            req = r.calls[0].request
            assert req.url == account_data_url
            assert req.method == 'PUT'


class TestUnbanApi:
    cli = MockClient("http://example.com")
    user_id = "@user:matrix.org"
    room_id = "#foo:matrix.org"

    async def test_unban(self):
        unban_url = "http://example.com" \
                    "/_matrix/client/r0/rooms/#foo:matrix.org/unban"
        body = '{"user_id": "' + self.user_id + '"}'
        with RequestsMock() as r:
            r.add(responses.POST, unban_url, body=body)
            await self.cli.api.unban_user(self.room_id, self.user_id)
            req = r.calls[0].request
            assert req.url == unban_url
            assert req.method == 'POST'
