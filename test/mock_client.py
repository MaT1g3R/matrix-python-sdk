from functools import partial

from requests import request
from matrix_client import client, api, errors


async def mock_request(self, method, endpoint, query_params, content, headers):
        print("called")
        kwargs = {key: val for key, val in {
            'params': query_params,
            'data': content,
            'headers': headers,
            'verify': self.validate_cert
        }.items() if val is not None}
        response = request(method, endpoint, **kwargs)
        if 200 <= response.status_code < 300:
            return api.MatrixHttpResponse(
                success=True,
                retry=None,
                body=response.json()
            )
        elif response.status_code == 429:
            return api.MatrixHttpResponse(
                success=False,
                retry=(response.json())["retry_after_ms"] / 1000,
                body=None
            )
        else:
            raise errors.MatrixRequestError(
                code=response.status_code,
                content=response.text
            )


class MockClient(client.MatrixClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api._try_send = partial(mock_request, self.api)
